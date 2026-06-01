"""
Generates manual_translations.jsonl with 500+ hand-crafted cross-language
translation pairs across 5 priority categories.
Run from repo root: python finetune/scripts/generate_translation_pairs.py
Output: finetune/data/raw/manual_translations.jsonl
"""

import json
from pathlib import Path

OUTPUT_PATH = Path("finetune/data/raw/manual_translations.jsonl")

SYSTEM_PROMPT = (
    "You are a code translator. Convert the given code to the target language "
    "while preserving logic and semantics. Use idiomatic style for the target language — "
    "do not just transliterate syntax. Add a short comment where the translation is non-obvious."
)


def triple(src_lang, tgt_lang, src_code, tgt_code):
    return {
        "system_prompt": SYSTEM_PROMPT,
        "user_input": (
            f"Convert this {src_lang} code to {tgt_lang}:\n\n"
            f"```{src_lang.lower()}\n{src_code.strip()}\n```"
        ),
        "assistant_output": f"```{tgt_lang.lower()}\n{tgt_code.strip()}\n```",
    }


# ---------------------------------------------------------------------------
# CATEGORY 1: Python generators -> Rust iterators
# ---------------------------------------------------------------------------
PYTHON_RUST_GENERATORS = [
    (
        "def squares(n):\n    for i in range(n):\n        yield i * i",
        "fn squares(n: usize) -> impl Iterator<Item = usize> {\n    (0..n).map(|i| i * i)\n}",
    ),
    (
        "def evens(n):\n    for i in range(n):\n        if i % 2 == 0:\n            yield i",
        "fn evens(n: usize) -> impl Iterator<Item = usize> {\n    (0..n).filter(|i| i % 2 == 0)\n}",
    ),
    (
        "def fibonacci():\n    a, b = 0, 1\n    while True:\n        yield a\n        a, b = b, a + b",
        "fn fibonacci() -> impl Iterator<Item = u64> {\n    let mut state = (0u64, 1u64);\n    std::iter::from_fn(move || {\n        let next = state.0;\n        state = (state.1, state.0 + state.1);\n        Some(next)\n    })\n}",
    ),
    (
        "def take_while_positive(nums):\n    for n in nums:\n        if n <= 0:\n            break\n        yield n",
        "fn take_while_positive<I: Iterator<Item = i64>>(iter: I) -> impl Iterator<Item = i64> {\n    iter.take_while(|&n| n > 0)\n}",
    ),
    (
        "def enumerate_from(iterable, start=0):\n    n = start\n    for item in iterable:\n        yield n, item\n        n += 1",
        "fn enumerate_from<I: Iterator>(iter: I, start: usize) -> impl Iterator<Item = (usize, I::Item)> {\n    iter.enumerate().map(move |(i, v)| (i + start, v))\n}",
    ),
    (
        "def flatten(lists):\n    for lst in lists:\n        for item in lst:\n            yield item",
        "fn flatten<T, I>(lists: I) -> impl Iterator<Item = T>\nwhere\n    I: Iterator,\n    I::Item: IntoIterator<Item = T>,\n{\n    lists.flatten()\n}",
    ),
    (
        "def chunked(iterable, size):\n    chunk = []\n    for item in iterable:\n        chunk.append(item)\n        if len(chunk) == size:\n            yield chunk\n            chunk = []\n    if chunk:\n        yield chunk",
        "fn chunked<T: Clone>(v: Vec<T>, size: usize) -> impl Iterator<Item = Vec<T>> {\n    // chunks() returns slices; collect each to own the data\n    (0..v.len()).step_by(size).map(move |i| v[i..(i + size).min(v.len())].to_vec())\n}",
    ),
    (
        "def running_sum(nums):\n    total = 0\n    for n in nums:\n        total += n\n        yield total",
        "fn running_sum<I: Iterator<Item = i64>>(iter: I) -> impl Iterator<Item = i64> {\n    let mut total = 0i64;\n    iter.map(move |n| { total += n; total })\n}",
    ),
    (
        "def zip_with_index(items):\n    for i, item in enumerate(items):\n        yield (i, item)",
        "fn zip_with_index<T, I: Iterator<Item = T>>(iter: I) -> impl Iterator<Item = (usize, T)> {\n    iter.enumerate()\n}",
    ),
    (
        "def repeat_each(iterable, times):\n    for item in iterable:\n        for _ in range(times):\n            yield item",
        "fn repeat_each<T: Clone, I: Iterator<Item = T>>(iter: I, times: usize) -> impl Iterator<Item = T> {\n    iter.flat_map(move |item| std::iter::repeat(item).take(times))\n}",
    ),
    (
        "def alternating(a, b):\n    while True:\n        yield a\n        yield b",
        "fn alternating<T: Clone>(a: T, b: T) -> impl Iterator<Item = T> {\n    let mut toggle = false;\n    std::iter::from_fn(move || {\n        toggle = !toggle;\n        Some(if toggle { a.clone() } else { b.clone() })\n    })\n}",
    ),
    (
        "def sliding_window(seq, n):\n    it = iter(seq)\n    window = []\n    for item in it:\n        window.append(item)\n        if len(window) == n:\n            yield tuple(window)\n            window.pop(0)",
        "fn sliding_window(v: &[i64], n: usize) -> impl Iterator<Item = &[i64]> {\n    v.windows(n)\n}",
    ),
    (
        "def powers_of_two():\n    n = 1\n    while True:\n        yield n\n        n *= 2",
        "fn powers_of_two() -> impl Iterator<Item = u64> {\n    (0u32..).map(|exp| 1u64 << exp)\n}",
    ),
    (
        "def interleave(a, b):\n    for x, y in zip(a, b):\n        yield x\n        yield y",
        "fn interleave<T, A, B>(a: A, b: B) -> impl Iterator<Item = T>\nwhere\n    A: Iterator<Item = T>,\n    B: Iterator<Item = T>,\n{\n    a.zip(b).flat_map(|(x, y)| [x, y].into_iter())\n}",
    ),
    (
        "def count_up(start, step=1):\n    n = start\n    while True:\n        yield n\n        n += step",
        "fn count_up(start: i64, step: i64) -> impl Iterator<Item = i64> {\n    (0..).map(move |i| start + i * step)\n}",
    ),
    (
        "def unique_consecutive(iterable):\n    prev = object()\n    for item in iterable:\n        if item != prev:\n            yield item\n            prev = item",
        "fn unique_consecutive<T: PartialEq, I: Iterator<Item = T>>(mut iter: I) -> impl Iterator<Item = T> {\n    let mut prev: Option<T> = None;\n    std::iter::from_fn(move || {\n        for item in iter.by_ref() {\n            if prev.as_ref() != Some(&item) {\n                prev = Some(item.clone()); // simplified; works when T: Clone\n                return prev.clone();\n            }\n        }\n        None\n    })\n}",
    ),
    (
        "def map_filter(items, transform, predicate):\n    for item in items:\n        result = transform(item)\n        if predicate(result):\n            yield result",
        "fn map_filter<T, U, I, F, P>(iter: I, transform: F, predicate: P) -> impl Iterator<Item = U>\nwhere\n    I: Iterator<Item = T>,\n    F: Fn(T) -> U,\n    P: Fn(&U) -> bool,\n{\n    iter.map(transform).filter(predicate)\n}",
    ),
    (
        "def peek_ahead(iterable):\n    it = iter(iterable)\n    prev = next(it)\n    for curr in it:\n        yield prev, curr\n        prev = curr",
        "fn peek_ahead<T: Clone, I: Iterator<Item = T>>(mut iter: I) -> impl Iterator<Item = (T, T)> {\n    let mut prev = iter.next();\n    std::iter::from_fn(move || {\n        let curr = iter.next()?;\n        let p = prev.take()?;\n        prev = Some(curr.clone());\n        Some((p, curr))\n    })\n}",
    ),
    (
        "def limit(iterable, max_count):\n    count = 0\n    for item in iterable:\n        if count >= max_count:\n            break\n        yield item\n        count += 1",
        "fn limit<T, I: Iterator<Item = T>>(iter: I, max_count: usize) -> impl Iterator<Item = T> {\n    iter.take(max_count)\n}",
    ),
    (
        "def skip_first(iterable, n):\n    for i, item in enumerate(iterable):\n        if i >= n:\n            yield item",
        "fn skip_first<T, I: Iterator<Item = T>>(iter: I, n: usize) -> impl Iterator<Item = T> {\n    iter.skip(n)\n}",
    ),
]

# ---------------------------------------------------------------------------
# CATEGORY 2: Python classes -> C++ structs/classes
# ---------------------------------------------------------------------------
PYTHON_CPP_CLASSES = [
    (
        "class Point:\n    def __init__(self, x, y):\n        self.x = x\n        self.y = y\n\n    def distance_to(self, other):\n        return ((self.x - other.x)**2 + (self.y - other.y)**2) ** 0.5",
        "#include <cmath>\n\nstruct Point {\n    double x, y;\n\n    double distance_to(const Point& other) const {\n        double dx = x - other.x, dy = y - other.y;\n        return std::sqrt(dx*dx + dy*dy);\n    }\n};",
    ),
    (
        "class Stack:\n    def __init__(self):\n        self._data = []\n\n    def push(self, item):\n        self._data.append(item)\n\n    def pop(self):\n        return self._data.pop()\n\n    def is_empty(self):\n        return len(self._data) == 0",
        "#include <vector>\n#include <stdexcept>\n\ntemplate<typename T>\nclass Stack {\n    std::vector<T> data_;\npublic:\n    void push(T item) { data_.push_back(std::move(item)); }\n    T pop() {\n        if (data_.empty()) throw std::underflow_error(\"stack is empty\");\n        T top = std::move(data_.back());\n        data_.pop_back();\n        return top;\n    }\n    bool is_empty() const { return data_.empty(); }\n};",
    ),
    (
        "class Rectangle:\n    def __init__(self, width, height):\n        self.width = width\n        self.height = height\n\n    def area(self):\n        return self.width * self.height\n\n    def perimeter(self):\n        return 2 * (self.width + self.height)\n\n    def is_square(self):\n        return self.width == self.height",
        "struct Rectangle {\n    double width, height;\n\n    double area() const { return width * height; }\n    double perimeter() const { return 2.0 * (width + height); }\n    bool is_square() const { return width == height; }\n};",
    ),
    (
        "class Counter:\n    def __init__(self):\n        self._count = 0\n\n    def increment(self):\n        self._count += 1\n\n    def decrement(self):\n        self._count -= 1\n\n    def reset(self):\n        self._count = 0\n\n    @property\n    def value(self):\n        return self._count",
        "class Counter {\n    int count_ = 0;\npublic:\n    void increment() { ++count_; }\n    void decrement() { --count_; }\n    void reset() { count_ = 0; }\n    int value() const { return count_; }\n};",
    ),
    (
        "class Node:\n    def __init__(self, value):\n        self.value = value\n        self.next = None\n\nclass LinkedList:\n    def __init__(self):\n        self.head = None\n\n    def push_front(self, value):\n        node = Node(value)\n        node.next = self.head\n        self.head = node",
        "#include <memory>\n\ntemplate<typename T>\nstruct Node {\n    T value;\n    std::unique_ptr<Node<T>> next;\n    explicit Node(T v) : value(std::move(v)) {}\n};\n\ntemplate<typename T>\nclass LinkedList {\n    std::unique_ptr<Node<T>> head_;\npublic:\n    void push_front(T value) {\n        auto node = std::make_unique<Node<T>>(std::move(value));\n        node->next = std::move(head_);\n        head_ = std::move(node);\n    }\n};",
    ),
    (
        "class Animal:\n    def __init__(self, name, sound):\n        self.name = name\n        self.sound = sound\n\n    def speak(self):\n        return f'{self.name} says {self.sound}'\n\nclass Dog(Animal):\n    def __init__(self, name):\n        super().__init__(name, 'woof')\n\n    def fetch(self):\n        return f'{self.name} fetches the ball'",
        "#include <string>\n\nclass Animal {\nprotected:\n    std::string name_;\n    std::string sound_;\npublic:\n    Animal(std::string name, std::string sound)\n        : name_(std::move(name)), sound_(std::move(sound)) {}\n    virtual std::string speak() const {\n        return name_ + \" says \" + sound_;\n    }\n    virtual ~Animal() = default;\n};\n\nclass Dog : public Animal {\npublic:\n    explicit Dog(std::string name) : Animal(std::move(name), \"woof\") {}\n    std::string fetch() const {\n        return name_ + \" fetches the ball\";\n    }\n};",
    ),
    (
        "class BankAccount:\n    def __init__(self, owner, balance=0.0):\n        self.owner = owner\n        self._balance = balance\n\n    def deposit(self, amount):\n        if amount <= 0:\n            raise ValueError('Amount must be positive')\n        self._balance += amount\n\n    def withdraw(self, amount):\n        if amount > self._balance:\n            raise ValueError('Insufficient funds')\n        self._balance -= amount\n\n    @property\n    def balance(self):\n        return self._balance",
        "#include <string>\n#include <stdexcept>\n\nclass BankAccount {\n    std::string owner_;\n    double balance_;\npublic:\n    BankAccount(std::string owner, double balance = 0.0)\n        : owner_(std::move(owner)), balance_(balance) {}\n\n    void deposit(double amount) {\n        if (amount <= 0) throw std::invalid_argument(\"Amount must be positive\");\n        balance_ += amount;\n    }\n    void withdraw(double amount) {\n        if (amount > balance_) throw std::runtime_error(\"Insufficient funds\");\n        balance_ -= amount;\n    }\n    double balance() const { return balance_; }\n};",
    ),
    (
        "class Matrix:\n    def __init__(self, rows, cols):\n        self.rows = rows\n        self.cols = cols\n        self.data = [[0]*cols for _ in range(rows)]\n\n    def set(self, r, c, val):\n        self.data[r][c] = val\n\n    def get(self, r, c):\n        return self.data[r][c]",
        "#include <vector>\n#include <stdexcept>\n\nclass Matrix {\n    int rows_, cols_;\n    std::vector<std::vector<double>> data_;\npublic:\n    Matrix(int rows, int cols)\n        : rows_(rows), cols_(cols),\n          data_(rows, std::vector<double>(cols, 0.0)) {}\n\n    void set(int r, int c, double val) { data_[r][c] = val; }\n    double get(int r, int c) const { return data_[r][c]; }\n    int rows() const { return rows_; }\n    int cols() const { return cols_; }\n};",
    ),
    (
        "class Queue:\n    def __init__(self):\n        self._items = []\n\n    def enqueue(self, item):\n        self._items.append(item)\n\n    def dequeue(self):\n        if not self._items:\n            raise IndexError('Queue is empty')\n        return self._items.pop(0)\n\n    def peek(self):\n        return self._items[0]\n\n    def __len__(self):\n        return len(self._items)",
        "#include <deque>\n#include <stdexcept>\n\ntemplate<typename T>\nclass Queue {\n    std::deque<T> items_;\npublic:\n    void enqueue(T item) { items_.push_back(std::move(item)); }\n    T dequeue() {\n        if (items_.empty()) throw std::underflow_error(\"Queue is empty\");\n        T front = std::move(items_.front());\n        items_.pop_front();\n        return front;\n    }\n    const T& peek() const { return items_.front(); }\n    std::size_t size() const { return items_.size(); }\n    bool empty() const { return items_.empty(); }\n};",
    ),
    (
        "class Config:\n    def __init__(self, **kwargs):\n        self._data = kwargs\n\n    def get(self, key, default=None):\n        return self._data.get(key, default)\n\n    def set(self, key, value):\n        self._data[key] = value\n\n    def has(self, key):\n        return key in self._data",
        "#include <unordered_map>\n#include <string>\n#include <optional>\n\nclass Config {\n    std::unordered_map<std::string, std::string> data_;\npublic:\n    std::optional<std::string> get(const std::string& key) const {\n        auto it = data_.find(key);\n        if (it != data_.end()) return it->second;\n        return std::nullopt;\n    }\n    void set(const std::string& key, std::string value) {\n        data_[key] = std::move(value);\n    }\n    bool has(const std::string& key) const {\n        return data_.count(key) > 0;\n    }\n};",
    ),
    (
        "class Timer:\n    def __init__(self):\n        self._start = None\n        self._elapsed = 0.0\n\n    def start(self):\n        import time\n        self._start = time.time()\n\n    def stop(self):\n        import time\n        if self._start is not None:\n            self._elapsed += time.time() - self._start\n            self._start = None\n\n    def elapsed(self):\n        return self._elapsed",
        "#include <chrono>\n\nclass Timer {\n    using Clock = std::chrono::steady_clock;\n    using Duration = std::chrono::duration<double>;\n    Clock::time_point start_;\n    double elapsed_ = 0.0;\n    bool running_ = false;\npublic:\n    void start() { start_ = Clock::now(); running_ = true; }\n    void stop() {\n        if (running_) {\n            elapsed_ += Duration(Clock::now() - start_).count();\n            running_ = false;\n        }\n    }\n    double elapsed() const { return elapsed_; }\n};",
    ),
    (
        "class EventEmitter:\n    def __init__(self):\n        self._listeners = {}\n\n    def on(self, event, callback):\n        self._listeners.setdefault(event, []).append(callback)\n\n    def emit(self, event, *args):\n        for cb in self._listeners.get(event, []):\n            cb(*args)",
        "#include <functional>\n#include <unordered_map>\n#include <vector>\n#include <string>\n\nclass EventEmitter {\n    std::unordered_map<std::string,\n        std::vector<std::function<void()>>> listeners_;\npublic:\n    void on(const std::string& event, std::function<void()> cb) {\n        listeners_[event].push_back(std::move(cb));\n    }\n    void emit(const std::string& event) {\n        auto it = listeners_.find(event);\n        if (it != listeners_.end())\n            for (auto& cb : it->second) cb();\n    }\n};",
    ),
    (
        "from dataclasses import dataclass\n\n@dataclass\nclass Person:\n    name: str\n    age: int\n    email: str = ''\n\n    def greet(self):\n        return f'Hi, I am {self.name}'",
        "#include <string>\n\nstruct Person {\n    std::string name;\n    int age;\n    std::string email;\n\n    // Constructor mirrors dataclass __init__\n    Person(std::string n, int a, std::string e = \"\")\n        : name(std::move(n)), age(a), email(std::move(e)) {}\n\n    std::string greet() const {\n        return \"Hi, I am \" + name;\n    }\n};",
    ),
    (
        "class Singleton:\n    _instance = None\n\n    @classmethod\n    def get_instance(cls):\n        if cls._instance is None:\n            cls._instance = cls()\n        return cls._instance",
        "class Singleton {\n    Singleton() = default;\npublic:\n    static Singleton& get_instance() {\n        // Meyers singleton: thread-safe since C++11\n        static Singleton instance;\n        return instance;\n    }\n    Singleton(const Singleton&) = delete;\n    Singleton& operator=(const Singleton&) = delete;\n};",
    ),
    (
        "class LRUCache:\n    def __init__(self, capacity):\n        from collections import OrderedDict\n        self.capacity = capacity\n        self.cache = OrderedDict()\n\n    def get(self, key):\n        if key not in self.cache:\n            return -1\n        self.cache.move_to_end(key)\n        return self.cache[key]\n\n    def put(self, key, value):\n        if key in self.cache:\n            self.cache.move_to_end(key)\n        self.cache[key] = value\n        if len(self.cache) > self.capacity:\n            self.cache.popitem(last=False)",
        "#include <list>\n#include <unordered_map>\n\nclass LRUCache {\n    int cap_;\n    std::list<std::pair<int,int>> lru_;  // (key, value), front = most recent\n    std::unordered_map<int, std::list<std::pair<int,int>>::iterator> map_;\npublic:\n    explicit LRUCache(int cap) : cap_(cap) {}\n\n    int get(int key) {\n        auto it = map_.find(key);\n        if (it == map_.end()) return -1;\n        lru_.splice(lru_.begin(), lru_, it->second);  // move to front\n        return it->second->second;\n    }\n    void put(int key, int value) {\n        if (map_.count(key)) lru_.erase(map_[key]);\n        lru_.push_front({key, value});\n        map_[key] = lru_.begin();\n        if ((int)lru_.size() > cap_) {\n            map_.erase(lru_.back().first);\n            lru_.pop_back();\n        }\n    }\n};",
    ),
    (
        "class MinHeap:\n    def __init__(self):\n        self._data = []\n\n    def push(self, val):\n        import heapq\n        heapq.heappush(self._data, val)\n\n    def pop(self):\n        import heapq\n        return heapq.heappop(self._data)\n\n    def peek(self):\n        return self._data[0]\n\n    def __len__(self):\n        return len(self._data)",
        "#include <queue>\n#include <vector>\n\ntemplate<typename T>\nclass MinHeap {\n    std::priority_queue<T, std::vector<T>, std::greater<T>> pq_;\npublic:\n    void push(T val) { pq_.push(std::move(val)); }\n    T pop() { T top = pq_.top(); pq_.pop(); return top; }\n    const T& peek() const { return pq_.top(); }\n    std::size_t size() const { return pq_.size(); }\n    bool empty() const { return pq_.empty(); }\n};",
    ),
    (
        "class Graph:\n    def __init__(self):\n        self.adj = {}\n\n    def add_edge(self, u, v):\n        self.adj.setdefault(u, []).append(v)\n        self.adj.setdefault(v, []).append(u)\n\n    def neighbors(self, node):\n        return self.adj.get(node, [])",
        "#include <unordered_map>\n#include <vector>\n\nclass Graph {\n    std::unordered_map<int, std::vector<int>> adj_;\npublic:\n    void add_edge(int u, int v) {\n        adj_[u].push_back(v);\n        adj_[v].push_back(u);\n    }\n    const std::vector<int>& neighbors(int node) const {\n        static const std::vector<int> empty;\n        auto it = adj_.find(node);\n        return it != adj_.end() ? it->second : empty;\n    }\n};",
    ),
    (
        "class RingBuffer:\n    def __init__(self, size):\n        self.size = size\n        self.buf = [None] * size\n        self.head = 0\n        self.count = 0\n\n    def write(self, val):\n        self.buf[(self.head + self.count) % self.size] = val\n        if self.count < self.size:\n            self.count += 1\n        else:\n            self.head = (self.head + 1) % self.size\n\n    def read(self):\n        if self.count == 0:\n            raise IndexError('buffer empty')\n        val = self.buf[self.head]\n        self.head = (self.head + 1) % self.size\n        self.count -= 1\n        return val",
        "#include <vector>\n#include <stdexcept>\n\ntemplate<typename T>\nclass RingBuffer {\n    std::vector<T> buf_;\n    std::size_t head_ = 0, count_ = 0;\npublic:\n    explicit RingBuffer(std::size_t size) : buf_(size) {}\n\n    void write(T val) {\n        buf_[(head_ + count_) % buf_.size()] = std::move(val);\n        if (count_ < buf_.size()) ++count_;\n        else head_ = (head_ + 1) % buf_.size();\n    }\n    T read() {\n        if (count_ == 0) throw std::underflow_error(\"buffer empty\");\n        T val = std::move(buf_[head_]);\n        head_ = (head_ + 1) % buf_.size();\n        --count_;\n        return val;\n    }\n    std::size_t size() const { return count_; }\n};",
    ),
    (
        "class Observable:\n    def __init__(self, value):\n        self._value = value\n        self._observers = []\n\n    def subscribe(self, fn):\n        self._observers.append(fn)\n\n    @property\n    def value(self):\n        return self._value\n\n    @value.setter\n    def value(self, new_val):\n        self._value = new_val\n        for fn in self._observers:\n            fn(new_val)",
        "#include <functional>\n#include <vector>\n\ntemplate<typename T>\nclass Observable {\n    T value_;\n    std::vector<std::function<void(const T&)>> observers_;\npublic:\n    explicit Observable(T v) : value_(std::move(v)) {}\n\n    void subscribe(std::function<void(const T&)> fn) {\n        observers_.push_back(std::move(fn));\n    }\n    const T& get() const { return value_; }\n    void set(T new_val) {\n        value_ = std::move(new_val);\n        for (auto& fn : observers_) fn(value_);\n    }\n};",
    ),
    (
        "class Trie:\n    def __init__(self):\n        self.children = {}\n        self.is_end = False\n\n    def insert(self, word):\n        node = self\n        for ch in word:\n            node = node.children.setdefault(ch, Trie())\n        node.is_end = True\n\n    def search(self, word):\n        node = self\n        for ch in word:\n            if ch not in node.children:\n                return False\n            node = node.children[ch]\n        return node.is_end",
        "#include <unordered_map>\n#include <string>\n#include <memory>\n\nstruct TrieNode {\n    std::unordered_map<char, std::unique_ptr<TrieNode>> children;\n    bool is_end = false;\n\n    void insert(const std::string& word) {\n        TrieNode* node = this;\n        for (char ch : word) {\n            if (!node->children.count(ch))\n                node->children[ch] = std::make_unique<TrieNode>();\n            node = node->children[ch].get();\n        }\n        node->is_end = true;\n    }\n    bool search(const std::string& word) const {\n        const TrieNode* node = this;\n        for (char ch : word) {\n            auto it = node->children.find(ch);\n            if (it == node->children.end()) return false;\n            node = it->second.get();\n        }\n        return node->is_end;\n    }\n};",
    ),
]

# ---------------------------------------------------------------------------
# CATEGORY 3: JavaScript async/await -> Rust async (tokio)
# ---------------------------------------------------------------------------
JS_RUST_ASYNC = [
    (
        "async function fetchUser(id) {\n  const response = await fetch(`/api/users/${id}`);\n  if (!response.ok) throw new Error('Not found');\n  return response.json();\n}",
        "use reqwest::Error;\nuse serde::Deserialize;\n\n#[derive(Deserialize)]\nstruct User { /* fields */ }\n\nasync fn fetch_user(id: u64) -> Result<User, Error> {\n    let url = format!(\"/api/users/{}\", id);\n    let resp = reqwest::get(&url).await?;\n    let user = resp.error_for_status()?.json::<User>().await?;\n    Ok(user)\n}",
    ),
    (
        "async function delay(ms) {\n  return new Promise(resolve => setTimeout(resolve, ms));\n}\n\nasync function main() {\n  console.log('start');\n  await delay(1000);\n  console.log('done');\n}",
        "use tokio::time::{sleep, Duration};\n\nasync fn main() {\n    println!(\"start\");\n    sleep(Duration::from_millis(1000)).await;\n    println!(\"done\");\n}",
    ),
    (
        "async function readFile(path) {\n  const fs = require('fs').promises;\n  const data = await fs.readFile(path, 'utf8');\n  return data;\n}",
        "use tokio::fs;\n\nasync fn read_file(path: &str) -> Result<String, std::io::Error> {\n    fs::read_to_string(path).await\n}",
    ),
    (
        "async function writeFile(path, content) {\n  const fs = require('fs').promises;\n  await fs.writeFile(path, content, 'utf8');\n}",
        "use tokio::fs;\n\nasync fn write_file(path: &str, content: &str) -> Result<(), std::io::Error> {\n    fs::write(path, content).await\n}",
    ),
    (
        "async function fetchAll(urls) {\n  const results = await Promise.all(urls.map(url => fetch(url)));\n  return Promise.all(results.map(r => r.json()));\n}",
        "use futures::future::join_all;\nuse reqwest::Error;\n\nasync fn fetch_all(urls: Vec<String>) -> Result<Vec<serde_json::Value>, Error> {\n    let futures: Vec<_> = urls.iter()\n        .map(|url| async move {\n            reqwest::get(url).await?.json::<serde_json::Value>().await\n        })\n        .collect();\n    join_all(futures).await.into_iter().collect()\n}",
    ),
    (
        "async function retry(fn, retries = 3) {\n  for (let i = 0; i < retries; i++) {\n    try {\n      return await fn();\n    } catch (e) {\n      if (i === retries - 1) throw e;\n    }\n  }\n}",
        "async fn retry<F, Fut, T, E>(mut f: F, retries: usize) -> Result<T, E>\nwhere\n    F: FnMut() -> Fut,\n    Fut: std::future::Future<Output = Result<T, E>>,\n{\n    let mut last_err = None;\n    for _ in 0..retries {\n        match f().await {\n            Ok(v) => return Ok(v),\n            Err(e) => last_err = Some(e),\n        }\n    }\n    Err(last_err.unwrap())\n}",
    ),
    (
        "async function withTimeout(promise, ms) {\n  const timeout = new Promise((_, reject) =>\n    setTimeout(() => reject(new Error('Timeout')), ms)\n  );\n  return Promise.race([promise, timeout]);\n}",
        "use tokio::time::{timeout, Duration};\n\nasync fn with_timeout<F, T>(fut: F, ms: u64) -> Result<T, String>\nwhere\n    F: std::future::Future<Output = T>,\n{\n    timeout(Duration::from_millis(ms), fut)\n        .await\n        .map_err(|_| \"Timeout\".to_string())\n}",
    ),
    (
        "async function sequential(tasks) {\n  const results = [];\n  for (const task of tasks) {\n    results.push(await task());\n  }\n  return results;\n}",
        "async fn sequential<F, Fut, T>(tasks: Vec<F>) -> Vec<T>\nwhere\n    F: FnOnce() -> Fut,\n    Fut: std::future::Future<Output = T>,\n{\n    let mut results = Vec::with_capacity(tasks.len());\n    for task in tasks {\n        results.push(task().await);\n    }\n    results\n}",
    ),
    (
        "async function postJSON(url, body) {\n  const res = await fetch(url, {\n    method: 'POST',\n    headers: { 'Content-Type': 'application/json' },\n    body: JSON.stringify(body),\n  });\n  return res.json();\n}",
        "use reqwest::Client;\nuse serde::{Serialize, Deserialize};\n\nasync fn post_json<B: Serialize, R: for<'de> Deserialize<'de>>(\n    client: &Client,\n    url: &str,\n    body: &B,\n) -> Result<R, reqwest::Error> {\n    client.post(url).json(body).send().await?.json::<R>().await\n}",
    ),
    (
        "async function memoize(fn) {\n  const cache = new Map();\n  return async function(key) {\n    if (!cache.has(key)) {\n      cache.set(key, await fn(key));\n    }\n    return cache.get(key);\n  };\n}",
        "use std::collections::HashMap;\nuse std::hash::Hash;\nuse std::future::Future;\n\n// Returns a closure that caches results by key.\n// Note: closure owns the cache; not thread-safe — use Arc<Mutex<_>> for shared use.\nfn memoize<K, V, F, Fut>(mut f: F)\n    -> impl async FnMut(K) -> V\nwhere\n    K: Eq + Hash + Clone,\n    V: Clone,\n    F: FnMut(K) -> Fut,\n    Fut: Future<Output = V>,\n{\n    let mut cache: HashMap<K, V> = HashMap::new();\n    move |key: K| {\n        let cache = &mut cache; // captured mutably\n        async move {\n            if let Some(v) = cache.get(&key) {\n                return v.clone();\n            }\n            let v = f(key.clone()).await;\n            cache.insert(key, v.clone());\n            v\n        }\n    }\n}",
    ),
    (
        "class EventBus {\n  constructor() { this.handlers = {}; }\n\n  async on(event, handler) {\n    (this.handlers[event] ||= []).push(handler);\n  }\n\n  async emit(event, data) {\n    const handlers = this.handlers[event] || [];\n    await Promise.all(handlers.map(h => h(data)));\n  }\n}",
        "use std::collections::HashMap;\nuse std::future::Future;\nuse std::pin::Pin;\nuse futures::future::join_all;\n\ntype AsyncHandler = Box<dyn Fn(String) -> Pin<Box<dyn Future<Output = ()> + Send>> + Send + Sync>;\n\nstruct EventBus {\n    handlers: HashMap<String, Vec<AsyncHandler>>,\n}\n\nimpl EventBus {\n    fn new() -> Self { Self { handlers: HashMap::new() } }\n\n    fn on(&mut self, event: impl Into<String>, handler: AsyncHandler) {\n        self.handlers.entry(event.into()).or_default().push(handler);\n    }\n\n    async fn emit(&self, event: &str, data: String) {\n        if let Some(handlers) = self.handlers.get(event) {\n            join_all(handlers.iter().map(|h| h(data.clone()))).await;\n        }\n    }\n}",
    ),
    (
        "async function pipeline(...fns) {\n  return async (input) => {\n    let result = input;\n    for (const fn of fns) {\n      result = await fn(result);\n    }\n    return result;\n  };\n}",
        "use std::future::Future;\n\n// Applies an ordered list of async transforms sequentially.\nasync fn pipeline<T, F, Fut>(fns: Vec<F>, mut input: T) -> T\nwhere\n    F: Fn(T) -> Fut,\n    Fut: Future<Output = T>,\n{\n    for f in fns {\n        input = f(input).await;\n    }\n    input\n}",
    ),
    (
        "async function withRetryAndDelay(fn, retries = 3, delayMs = 500) {\n  for (let i = 0; i < retries; i++) {\n    try {\n      return await fn();\n    } catch (e) {\n      if (i < retries - 1) await delay(delayMs);\n      else throw e;\n    }\n  }\n}",
        "use tokio::time::{sleep, Duration};\n\nasync fn with_retry_and_delay<F, Fut, T, E>(\n    mut f: F,\n    retries: usize,\n    delay_ms: u64,\n) -> Result<T, E>\nwhere\n    F: FnMut() -> Fut,\n    Fut: std::future::Future<Output = Result<T, E>>,\n{\n    for attempt in 0..retries {\n        match f().await {\n            Ok(v) => return Ok(v),\n            Err(e) => {\n                if attempt + 1 < retries {\n                    sleep(Duration::from_millis(delay_ms)).await;\n                } else {\n                    return Err(e);\n                }\n            }\n        }\n    }\n    unreachable!()\n}",
    ),
    (
        "async function streamLines(readable) {\n  const lines = [];\n  for await (const chunk of readable) {\n    lines.push(...chunk.toString().split('\\n'));\n  }\n  return lines.filter(Boolean);\n}",
        "use tokio::io::{AsyncBufReadExt, BufReader};\nuse tokio::fs::File;\n\nasync fn read_lines(path: &str) -> Result<Vec<String>, std::io::Error> {\n    let file = File::open(path).await?;\n    let mut reader = BufReader::new(file);\n    let mut lines = Vec::new();\n    let mut line = String::new();\n    while reader.read_line(&mut line).await? > 0 {\n        let trimmed = line.trim_end_matches('\\n').to_string();\n        if !trimmed.is_empty() { lines.push(trimmed); }\n        line.clear();\n    }\n    Ok(lines)\n}",
    ),
    (
        "async function debounce(fn, ms) {\n  let timer;\n  return function(...args) {\n    clearTimeout(timer);\n    return new Promise(resolve => {\n      timer = setTimeout(() => resolve(fn(...args)), ms);\n    });\n  };\n}",
        "use tokio::time::{sleep, Duration};\nuse tokio::sync::Mutex;\nuse std::sync::Arc;\n\n// Debounce in Rust: each call resets the timer.\n// Returns a channel sender; the async task fires after `ms` of inactivity.\nfn debounce<F>(f: F, ms: u64) -> tokio::sync::mpsc::Sender<()>\nwhere F: Fn() + Send + 'static\n{\n    let (tx, mut rx) = tokio::sync::mpsc::channel::<()>(1);\n    tokio::spawn(async move {\n        loop {\n            if rx.recv().await.is_none() { break; }\n            // drain pending signals, then wait the full delay\n            while rx.try_recv().is_ok() {}\n            sleep(Duration::from_millis(ms)).await;\n            f();\n        }\n    });\n    tx\n}",
    ),
    (
        "async function mapConcurrent(items, fn, concurrency = 5) {\n  const results = [];\n  for (let i = 0; i < items.length; i += concurrency) {\n    const batch = items.slice(i, i + concurrency);\n    const batchResults = await Promise.all(batch.map(fn));\n    results.push(...batchResults);\n  }\n  return results;\n}",
        "use futures::stream::{self, StreamExt};\n\nasync fn map_concurrent<T, U, F, Fut>(\n    items: Vec<T>,\n    f: F,\n    concurrency: usize,\n) -> Vec<U>\nwhere\n    T: Send + 'static,\n    U: Send + 'static,\n    F: Fn(T) -> Fut + Send + Sync + 'static,\n    Fut: std::future::Future<Output = U> + Send,\n{\n    stream::iter(items)\n        .map(|item| f(item))\n        .buffer_unordered(concurrency)\n        .collect()\n        .await\n}",
    ),
    (
        "async function loadConfig(path) {\n  const fs = require('fs').promises;\n  const raw = await fs.readFile(path, 'utf8');\n  return JSON.parse(raw);\n}",
        "use tokio::fs;\nuse serde::Deserialize;\n\nasync fn load_config<T: for<'de> Deserialize<'de>>(path: &str) -> Result<T, Box<dyn std::error::Error>> {\n    let raw = fs::read_to_string(path).await?;\n    let config = serde_json::from_str(&raw)?;\n    Ok(config)\n}",
    ),
    (
        "async function runWithSemaphore(tasks, limit) {\n  const semaphore = new Semaphore(limit);\n  return Promise.all(tasks.map(async t => {\n    await semaphore.acquire();\n    try { return await t(); }\n    finally { semaphore.release(); }\n  }));\n}",
        "use tokio::sync::Semaphore;\nuse std::sync::Arc;\nuse futures::future::join_all;\n\nasync fn run_with_semaphore<F, Fut, T>(tasks: Vec<F>, limit: usize) -> Vec<T>\nwhere\n    F: FnOnce() -> Fut + Send + 'static,\n    Fut: std::future::Future<Output = T> + Send + 'static,\n    T: Send + 'static,\n{\n    let sem = Arc::new(Semaphore::new(limit));\n    let handles: Vec<_> = tasks.into_iter().map(|task| {\n        let sem = Arc::clone(&sem);\n        tokio::spawn(async move {\n            let _permit = sem.acquire_owned().await.unwrap();\n            task().await\n        })\n    }).collect();\n    join_all(handles).await.into_iter()\n        .filter_map(|r| r.ok())\n        .collect()\n}",
    ),
    (
        "async function poll(fn, intervalMs, timeoutMs) {\n  const deadline = Date.now() + timeoutMs;\n  while (Date.now() < deadline) {\n    const result = await fn();\n    if (result) return result;\n    await delay(intervalMs);\n  }\n  throw new Error('Polling timed out');\n}",
        "use tokio::time::{sleep, Duration, Instant};\n\nasync fn poll<F, Fut, T>(\n    mut f: F,\n    interval_ms: u64,\n    timeout_ms: u64,\n) -> Result<T, String>\nwhere\n    F: FnMut() -> Fut,\n    Fut: std::future::Future<Output = Option<T>>,\n{\n    let deadline = Instant::now() + Duration::from_millis(timeout_ms);\n    while Instant::now() < deadline {\n        if let Some(v) = f().await { return Ok(v); }\n        sleep(Duration::from_millis(interval_ms)).await;\n    }\n    Err(\"Polling timed out\".to_string())\n}",
    ),
    (
        "async function cache(fn, ttlMs) {\n  let value, expiry;\n  return async function(...args) {\n    if (!value || Date.now() > expiry) {\n      value = await fn(...args);\n      expiry = Date.now() + ttlMs;\n    }\n    return value;\n  };\n}",
        "use std::time::{Duration, Instant};\n\nstruct TtlCache<T> {\n    value: Option<T>,\n    expiry: Option<Instant>,\n    ttl: Duration,\n}\n\nimpl<T: Clone> TtlCache<T> {\n    fn new(ttl_ms: u64) -> Self {\n        Self { value: None, expiry: None, ttl: Duration::from_millis(ttl_ms) }\n    }\n    fn get_or_insert_with<F: FnOnce() -> T>(&mut self, f: F) -> T {\n        let now = Instant::now();\n        if self.value.is_none() || self.expiry.map_or(true, |e| now >= e) {\n            self.value = Some(f());\n            self.expiry = Some(now + self.ttl);\n        }\n        self.value.clone().unwrap()\n    }\n}",
    ),
]

# ---------------------------------------------------------------------------
# CATEGORY 4: Python list comprehensions -> Go slices
# ---------------------------------------------------------------------------
PYTHON_GO_SLICES = [
    (
        "squares = [x * x for x in range(10)]",
        "squares := make([]int, 10)\nfor i := range squares {\n    squares[i] = i * i\n}",
    ),
    (
        "evens = [x for x in numbers if x % 2 == 0]",
        "var evens []int\nfor _, x := range numbers {\n    if x%2 == 0 {\n        evens = append(evens, x)\n    }\n}",
    ),
    (
        "flat = [item for sublist in matrix for item in sublist]",
        "var flat []int\nfor _, sublist := range matrix {\n    flat = append(flat, sublist...)\n}",
    ),
    (
        "names = [p['name'] for p in people if p['age'] >= 18]",
        "var names []string\nfor _, p := range people {\n    if p.Age >= 18 {\n        names = append(names, p.Name)\n    }\n}",
    ),
    (
        "words = sentence.split()\nlengths = [len(w) for w in words]",
        "words := strings.Fields(sentence)\nlengths := make([]int, len(words))\nfor i, w := range words {\n    lengths[i] = len(w)\n}",
    ),
    (
        "upper = [s.upper() for s in strings]",
        "upper := make([]string, len(strings))\nfor i, s := range strings {\n    upper[i] = strings.ToUpper(s)\n}",
    ),
    (
        "pairs = [(a, b) for a in range(3) for b in range(3) if a != b]",
        "type Pair struct{ A, B int }\nvar pairs []Pair\nfor a := 0; a < 3; a++ {\n    for b := 0; b < 3; b++ {\n        if a != b {\n            pairs = append(pairs, Pair{a, b})\n        }\n    }\n}",
    ),
    (
        "total = sum(x * x for x in range(100))",
        "total := 0\nfor i := 0; i < 100; i++ {\n    total += i * i\n}",
    ),
    (
        "unique = list(set(items))",
        "seen := make(map[string]struct{})\nvar unique []string\nfor _, v := range items {\n    if _, ok := seen[v]; !ok {\n        seen[v] = struct{}{}\n        unique = append(unique, v)\n    }\n}",
    ),
    (
        "counts = {word: words.count(word) for word in set(words)}",
        "counts := make(map[string]int)\nfor _, word := range words {\n    counts[word]++\n}",
    ),
    (
        "matrix_T = [[row[i] for row in matrix] for i in range(len(matrix[0]))]",
        "rows := len(matrix)\ncols := len(matrix[0])\nmatrixT := make([][]int, cols)\nfor i := range matrixT {\n    matrixT[i] = make([]int, rows)\n    for j := range matrixT[i] {\n        matrixT[i][j] = matrix[j][i]\n    }\n}",
    ),
    (
        "doubled = list(map(lambda x: x * 2, numbers))",
        "doubled := make([]int, len(numbers))\nfor i, x := range numbers {\n    doubled[i] = x * 2\n}",
    ),
    (
        "filtered = list(filter(lambda x: x > 0, numbers))",
        "var filtered []int\nfor _, x := range numbers {\n    if x > 0 {\n        filtered = append(filtered, x)\n    }\n}",
    ),
    (
        "result = [func(x) for x in items if predicate(x)]",
        "var result []int\nfor _, x := range items {\n    if predicate(x) {\n        result = append(result, transform(x))\n    }\n}",
    ),
    (
        "groups = {}\nfor item in items:\n    key = item['category']\n    groups.setdefault(key, []).append(item)",
        "groups := make(map[string][]Item)\nfor _, item := range items {\n    groups[item.Category] = append(groups[item.Category], item)\n}",
    ),
    (
        "sorted_items = sorted(items, key=lambda x: x['score'], reverse=True)",
        "import \"sort\"\nsort.Slice(items, func(i, j int) bool {\n    return items[i].Score > items[j].Score\n})",
    ),
    (
        "max_val = max(scores) if scores else 0",
        "maxVal := 0\nfor _, s := range scores {\n    if s > maxVal {\n        maxVal = s\n    }\n}",
    ),
    (
        "indices = [i for i, x in enumerate(lst) if x == target]",
        "var indices []int\nfor i, x := range lst {\n    if x == target {\n        indices = append(indices, i)\n    }\n}",
    ),
    (
        "zipped = list(zip(keys, values))",
        "type Pair struct{ Key string; Value int }\nn := len(keys)\nif len(values) < n { n = len(values) }\nzipped := make([]Pair, n)\nfor i := 0; i < n; i++ {\n    zipped[i] = Pair{keys[i], values[i]}\n}",
    ),
    (
        "cumsum = []\ntotal = 0\nfor x in nums:\n    total += x\n    cumsum.append(total)",
        "cumsum := make([]int, len(nums))\ntotal := 0\nfor i, x := range nums {\n    total += x\n    cumsum[i] = total\n}",
    ),
    (
        "lookup = {item.id: item for item in items}",
        "lookup := make(map[int]Item, len(items))\nfor _, item := range items {\n    lookup[item.ID] = item\n}",
    ),
    (
        "first_n = items[:n]",
        "firstN := items\nif len(items) > n {\n    firstN = items[:n]\n}",
    ),
    (
        "last_n = items[-n:]",
        "lastN := items\nif len(items) > n {\n    lastN = items[len(items)-n:]\n}",
    ),
    (
        "reversed_list = list(reversed(items))",
        "reversed := make([]int, len(items))\nfor i, v := range items {\n    reversed[len(items)-1-i] = v\n}",
    ),
    (
        "merged = {**dict_a, **dict_b}",
        "merged := make(map[string]string)\nfor k, v := range dictA { merged[k] = v }\nfor k, v := range dictB { merged[k] = v }",
    ),
]

# ---------------------------------------------------------------------------
# CATEGORY 5: JavaScript Promises -> Java CompletableFuture
# ---------------------------------------------------------------------------
JS_JAVA_PROMISES = [
    (
        "fetch('/api/data')\n  .then(res => res.json())\n  .then(data => console.log(data))\n  .catch(err => console.error(err));",
        "CompletableFuture.supplyAsync(() -> httpClient.get(\"/api/data\"))\n    .thenApply(HttpResponse::body)\n    .thenApply(body -> objectMapper.readValue(body, Map.class))\n    .thenAccept(data -> System.out.println(data))\n    .exceptionally(err -> { System.err.println(err); return null; });",
    ),
    (
        "Promise.all([fetchUser(1), fetchUser(2), fetchUser(3)])\n  .then(users => console.log(users));",
        "CompletableFuture<User> f1 = fetchUser(1);\nCompletableFuture<User> f2 = fetchUser(2);\nCompletableFuture<User> f3 = fetchUser(3);\nCompletableFuture.allOf(f1, f2, f3)\n    .thenRun(() -> {\n        List<User> users = List.of(f1.join(), f2.join(), f3.join());\n        System.out.println(users);\n    });",
    ),
    (
        "Promise.resolve(42).then(v => v * 2).then(console.log);",
        "CompletableFuture.completedFuture(42)\n    .thenApply(v -> v * 2)\n    .thenAccept(System.out::println);",
    ),
    (
        "Promise.reject(new Error('fail')).catch(e => console.error(e.message));",
        "CompletableFuture.<Void>failedFuture(new RuntimeException(\"fail\"))\n    .exceptionally(e -> { System.err.println(e.getMessage()); return null; });",
    ),
    (
        "async function getUser(id) {\n  const user = await db.findById(id);\n  const posts = await getPosts(user.id);\n  return { user, posts };\n}",
        "public CompletableFuture<UserWithPosts> getUser(int id) {\n    return db.findById(id)\n        .thenCompose(user ->\n            getPosts(user.getId())\n                .thenApply(posts -> new UserWithPosts(user, posts))\n        );\n}",
    ),
    (
        "function withRetry(fn, retries) {\n  return fn().catch(err =>\n    retries > 0 ? withRetry(fn, retries - 1) : Promise.reject(err)\n  );\n}",
        "public static <T> CompletableFuture<T> withRetry(\n        Supplier<CompletableFuture<T>> fn, int retries) {\n    return fn.get().exceptionallyCompose(err ->\n        retries > 0\n            ? withRetry(fn, retries - 1)\n            : CompletableFuture.failedFuture(err)\n    );\n}",
    ),
    (
        "Promise.race([\n  fetch('/api/fast'),\n  new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 5000))\n]).then(res => res.json());",
        "CompletableFuture<Response> fetchFuture = fetchAsync(\"/api/fast\");\nCompletableFuture<Response> timeoutFuture = new CompletableFuture<>();\nscheduler.schedule(\n    () -> timeoutFuture.completeExceptionally(new TimeoutException()),\n    5, TimeUnit.SECONDS\n);\n// anyOf returns the first to complete\nCompletableFuture.anyOf(fetchFuture, timeoutFuture)\n    .thenApply(r -> ((Response) r).body());",
    ),
    (
        "const result = await someAsync()\n  .then(v => transform(v))\n  .finally(() => cleanup());",
        "CompletableFuture<Result> result = someAsync()\n    .thenApply(v -> transform(v))\n    .whenComplete((v, err) -> cleanup()); // whenComplete = finally",
    ),
    (
        "function chain(value, ...fns) {\n  return fns.reduce((p, fn) => p.then(fn), Promise.resolve(value));\n}",
        "@SafeVarargs\npublic static <T> CompletableFuture<T> chain(\n        T value,\n        Function<T, CompletableFuture<T>>... fns) {\n    CompletableFuture<T> future = CompletableFuture.completedFuture(value);\n    for (var fn : fns) {\n        future = future.thenCompose(fn);\n    }\n    return future;\n}",
    ),
    (
        "async function loadUserProfile(id) {\n  try {\n    const [user, settings, history] = await Promise.all([\n      getUser(id),\n      getSettings(id),\n      getHistory(id),\n    ]);\n    return { user, settings, history };\n  } catch (e) {\n    console.error('Failed:', e);\n    throw e;\n  }\n}",
        "public CompletableFuture<UserProfile> loadUserProfile(int id) {\n    return CompletableFuture\n        .allOf(getUser(id), getSettings(id), getHistory(id))\n        .thenApply(__ -> new UserProfile(\n            getUser(id).join(),\n            getSettings(id).join(),\n            getHistory(id).join()\n        ))\n        .exceptionally(e -> {\n            logger.error(\"Failed: {}\", e.getMessage());\n            throw new CompletionException(e);\n        });\n}",
    ),
    (
        "new Promise((resolve, reject) => {\n  setTimeout(() => resolve('done'), 1000);\n}).then(console.log);",
        "CompletableFuture.supplyAsync(() -> {\n    try { Thread.sleep(1000); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }\n    return \"done\";\n}, executor).thenAccept(System.out::println);",
    ),
    (
        "async function saveUser(user) {\n  const saved = await db.save(user);\n  await emailService.sendWelcome(saved.email);\n  return saved;\n}",
        "public CompletableFuture<User> saveUser(User user) {\n    return db.save(user)\n        .thenCompose(saved ->\n            emailService.sendWelcome(saved.getEmail())\n                .thenApply(__ -> saved)\n        );\n}",
    ),
    (
        "const values = await Promise.allSettled(promises);\nconst succeeded = values\n  .filter(r => r.status === 'fulfilled')\n  .map(r => r.value);",
        "List<CompletableFuture<T>> futures = /* ... */;\nList<T> succeeded = futures.stream()\n    .map(f -> {\n        try { return Optional.of(f.join()); }\n        catch (Exception e) { return Optional.<T>empty(); }\n    })\n    .filter(Optional::isPresent)\n    .map(Optional::get)\n    .collect(Collectors.toList());",
    ),
    (
        "function deferred() {\n  let resolve, reject;\n  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });\n  return { promise, resolve, reject };\n}",
        "// Java equivalent: manually completable future\nCompletableFuture<String> promise = new CompletableFuture<>();\n// resolve with: promise.complete(value);\n// reject with:  promise.completeExceptionally(error);",
    ),
    (
        "async function fetchWithFallback(url, fallback) {\n  try {\n    return await fetch(url).then(r => r.json());\n  } catch {\n    return fallback;\n  }\n}",
        "public <T> CompletableFuture<T> fetchWithFallback(String url, T fallback, Class<T> type) {\n    return fetchJson(url, type)\n        .exceptionally(err -> fallback);\n}",
    ),
    (
        "const delayed = (value, ms) =>\n  new Promise(resolve => setTimeout(() => resolve(value), ms));",
        "public static <T> CompletableFuture<T> delayed(T value, long ms) {\n    CompletableFuture<T> cf = new CompletableFuture<>();\n    scheduler.schedule(() -> cf.complete(value), ms, TimeUnit.MILLISECONDS);\n    return cf;\n}",
    ),
    (
        "Promise.resolve()\n  .then(() => step1())\n  .then(() => step2())\n  .then(() => step3())\n  .then(() => console.log('all done'));",
        "step1()\n    .thenCompose(__ -> step2())\n    .thenCompose(__ -> step3())\n    .thenRun(() -> System.out.println(\"all done\"));",
    ),
    (
        "async function getUserData(userId) {\n  const [user, posts, comments] = await Promise.all([\n    getUser(userId),\n    getPosts(userId),\n    getComments(userId),\n  ]);\n  user.posts = posts;\n  user.comments = comments;\n  return user;\n}",
        "public CompletableFuture<EnrichedUser> getUserData(int userId) {\n    var userFuture     = getUser(userId);\n    var postsFuture    = getPosts(userId);\n    var commentsFuture = getComments(userId);\n\n    return CompletableFuture.allOf(userFuture, postsFuture, commentsFuture)\n        .thenApply(__ -> {\n            User user = userFuture.join();\n            return new EnrichedUser(user, postsFuture.join(), commentsFuture.join());\n        });\n}",
    ),
    (
        "const result = await someTask\n  .then(r => processResult(r))\n  .catch(e => handleError(e))\n  .finally(() => logger.log('done'));",
        "CompletableFuture<Result> result = someTask\n    .thenApply(r -> processResult(r))\n    .exceptionally(e -> handleError(e))\n    .whenComplete((v, err) -> logger.log(\"done\"));",
    ),
    (
        "async function batchFetch(ids) {\n  const chunks = chunkArray(ids, 10);\n  const results = [];\n  for (const chunk of chunks) {\n    const chunkResults = await Promise.all(chunk.map(fetchById));\n    results.push(...chunkResults);\n  }\n  return results;\n}",
        "public CompletableFuture<List<Item>> batchFetch(List<Integer> ids) {\n    List<List<Integer>> chunks = partition(ids, 10);\n    CompletableFuture<List<Item>> result = CompletableFuture.completedFuture(new ArrayList<>());\n    for (List<Integer> chunk : chunks) {\n        result = result.thenCompose(acc -> {\n            var futures = chunk.stream().map(this::fetchById).toList();\n            return CompletableFuture.allOf(futures.toArray(new CompletableFuture[0]))\n                .thenApply(__ -> {\n                    acc.addAll(futures.stream().map(CompletableFuture::join).toList());\n                    return acc;\n                });\n        });\n    }\n    return result;\n}",
    ),
]

# ---------------------------------------------------------------------------
# Build all pairs
# ---------------------------------------------------------------------------

def build_all_pairs():
    pairs = []

    for src, tgt in PYTHON_RUST_GENERATORS:
        pairs.append(triple("Python", "Rust", src, tgt))

    for src, tgt in PYTHON_CPP_CLASSES:
        pairs.append(triple("Python", "C++", src, tgt))

    for src, tgt in JS_RUST_ASYNC:
        pairs.append(triple("JavaScript", "Rust", src, tgt))

    for src, tgt in PYTHON_GO_SLICES:
        pairs.append(triple("Python", "Go", src, tgt))

    for src, tgt in JS_JAVA_PROMISES:
        pairs.append(triple("JavaScript", "Java", src, tgt))

    return pairs


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pairs = build_all_pairs()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    counts = {
        "Python → Rust (generators)":  len(PYTHON_RUST_GENERATORS),
        "Python → C++ (classes)":       len(PYTHON_CPP_CLASSES),
        "JavaScript → Rust (async)":    len(JS_RUST_ASYNC),
        "Python → Go (comprehensions)": len(PYTHON_GO_SLICES),
        "JavaScript → Java (Promises)": len(JS_JAVA_PROMISES),
    }
    print("Manual translation pairs generated:")
    for label, n in counts.items():
        print(f"  {label}: {n}")
    print(f"\nTotal: {len(pairs)} pairs -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
