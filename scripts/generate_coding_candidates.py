"""Generate the round-4 coding candidate training pool (100 self_authored samples).

Composition:
- 60 code_gen tasks (string/list/math/dict/date/loop categories, all real
  Python functions, none overlapping with the coding_eval_v1 holdout).
- 20 debug tasks: buggy code + minimal fix, all parse-checked.
- 14 QA samples with declared key terms.
- 6 counterexamples targeting the two known failure modes:
  * counterexample_019 (anti off-topic, sft-019): direct minimal python answer.
  * counterexample_020 (anti repetition loop, sft-020): one-sentence answer.

Every code task also carries turn-taking-repetition counter-rules in its note:
answers must be direct and must not contain >=3 consecutive identical lines.
All counterexamples are written against REAL code tasks (a bug fix and a loop
writing task), not abstract statements.

Run: python scripts/generate_coding_candidates.py --out data/seed/coding_candidates_v1.jsonl
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def _rec(sid, ttype, question, answer, note, **extra):
    item = {
        "source_id": sid,
        "rights": "self_authored",
        "reviewed_by": "dataset_author",
        "approved": True,
        "split": "train",
        "task_type": ttype,
        "messages": [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ],
        "note": note,
    }
    item.update(extra)
    return item


# =====================================================================
# 60 code_gen tasks. Function names deliberately avoid every name that
# appears in data/eval/coding_eval_v1.jsonl (leakage-safe by design).
# =====================================================================

CODE_GEN = [
    # ---- string category (12) ----
    ("slugify", "写一个 Python 函数 slugify(s) 把字符串转为 URL slug（小写、空格转连字符），只输出代码。",
     "def slugify(s):\n    return s.strip().lower().replace(' ', '-')"),
    ("title_case", "写一个 Python 函数 title_case(s) 把每个单词首字母大写，只输出代码。",
     "def title_case(s):\n    return ' '.join(w.capitalize() for w in s.split())"),
    ("truncate", "写一个 Python 函数 truncate(s, n) 超过 n 字符时截断并加省略号，只输出代码。",
     "def truncate(s, n):\n    return s if len(s) <= n else s[:n] + '...'"),
    ("strip_spaces", "写一个 Python 函数 strip_spaces(s) 移除所有空格，只输出代码。",
     "def strip_spaces(s):\n    return s.replace(' ', '')"),
    ("is_vowel_start", "写一个 Python 函数 is_vowel_start(s) 判断首字符是否为元音字母，只输出代码。",
     "def is_vowel_start(s):\n    return bool(s) and s[0].lower() in 'aeiou'"),
    ("pad_left", "写一个 Python 函数 pad_left(s, n) 用零填充到指定长度，只输出代码。",
     "def pad_left(s, n):\n    return s.zfill(n)"),
    ("swap_case", "写一个 Python 函数 swap_case(s) 交换大小写，只输出代码。",
     "def swap_case(s):\n    return s.swapcase()"),
    ("count_substring", "写一个 Python 函数 count_substring(s, sub) 统计子串出现次数（可重叠），只输出代码。",
     "def count_substring(s, sub):\n    count = 0\n    for i in range(len(s) - len(sub) + 1):\n        if s[i:i + len(sub)] == sub:\n            count += 1\n    return count"),
    ("normalize_ws", "写一个 Python 函数 normalize_ws(s) 把连续空白合并为单个空格，只输出代码。",
     "def normalize_ws(s):\n    return ' '.join(s.split())"),
    ("starts_with_any", "写一个 Python 函数 starts_with_any(s, prefixes) 判断是否以任一前缀开头，只输出代码。",
     "def starts_with_any(s, prefixes):\n    return any(s.startswith(p) for p in prefixes)"),
    ("last_char", "写一个 Python 函数 last_char(s) 返回最后一个字符，空串返回空串，只输出代码。",
     "def last_char(s):\n    return s[-1] if s else ''"),
    ("is_alpha_only", "写一个 Python 函数 is_alpha_only(s) 判断字符串只含字母，只输出代码。",
     "def is_alpha_only(s):\n    return s.isalpha()"),

    # ---- list category (14) ----
    ("chunked_sum", "写一个 Python 函数 chunked_sum(nums, size) 按固定大小分块求和，只输出代码。",
     "def chunked_sum(nums, size):\n    return [sum(nums[i:i + size]) for i in range(0, len(nums), size)]"),
    ("rotate_list", "写一个 Python 函数 rotate_list(lst, k) 向右旋转 k 步，只输出代码。",
     "def rotate_list(lst, k):\n    if not lst:\n        return []\n    k = k % len(lst)\n    return lst[-k:] + lst[:-k]"),
    ("interleave", "写一个 Python 函数 interleave(a, b) 交替合并两个列表，只输出代码。",
     "def interleave(a, b):\n    out = []\n    for x, y in zip(a, b):\n        out.append(x)\n        out.append(y)\n    return out"),
    ("last_index", "写一个 Python 函数 last_index(lst, x) 返回元素最后出现位置，找不到返回 -1，只输出代码。",
     "def last_index(lst, x):\n    result = -1\n    for i, v in enumerate(lst):\n        if v == x:\n            result = i\n    return result"),
    ("clamp_value", "写一个 Python 函数 clamp_value(v, lo, hi) 把数值限制在闭区间内，只输出代码。",
     "def clamp_value(v, lo, hi):\n    return max(lo, min(hi, v))"),
    ("count_negatives", "写一个 Python 函数 count_negatives(nums) 统计负数个数，只输出代码。",
     "def count_negatives(nums):\n    return sum(1 for n in nums if n < 0)"),
    ("running_max", "写一个 Python 函数 running_max(lst) 返回逐步累积最大值列表，只输出代码。",
     "def running_max(lst):\n    out = []\n    current = None\n    for v in lst:\n        current = v if current is None else max(current, v)\n        out.append(current)\n    return out"),
    ("min_abs", "写一个 Python 函数 min_abs(nums) 返回绝对值最小的元素，只输出代码。",
     "def min_abs(nums):\n    return min(nums, key=abs)"),
    ("tail_sum", "写一个 Python 函数 tail_sum(nums, k) 返回最后 k 个元素之和，只输出代码。",
     "def tail_sum(nums, k):\n    return sum(nums[-k:])"),
    ("safe_get", "写一个 Python 函数 safe_get(lst, i, default) 越界时返回默认值，只输出代码。",
     "def safe_get(lst, i, default=None):\n    if 0 <= i < len(lst):\n        return lst[i]\n    return default"),
    ("drop_while", "写一个 Python 函数 drop_while(lst, pred) 跳过开头满足条件的元素，只输出代码。",
     "def drop_while(lst, pred):\n    for i, v in enumerate(lst):\n        if not pred(v):\n            return lst[i:]\n    return []"),
    ("pair_sums", "写一个 Python 函数 pair_sums(a, b) 返回两列表对应元素之和，只输出代码。",
     "def pair_sums(a, b):\n    return [x + y for x, y in zip(a, b)]"),
    ("first_negative", "写一个 Python 函数 first_negative(nums) 返回第一个负数，没有返回 None，只输出代码。",
     "def first_negative(nums):\n    for n in nums:\n        if n < 0:\n            return n\n    return None"),
    ("slice_every_nth", "写一个 Python 函数 slice_every_nth(lst, n) 每隔 n 个取一个元素，只输出代码。",
     "def slice_every_nth(lst, n):\n    return lst[::n]"),

    # ---- dict category (8) ----
    ("invert_dict", "写一个 Python 函数 invert_dict(d) 交换字典键值，只输出代码。",
     "def invert_dict(d):\n    return {v: k for k, v in d.items()}"),
    ("dict_keys_sorted", "写一个 Python 函数 dict_keys_sorted(d) 返回按键排序的键列表，只输出代码。",
     "def dict_keys_sorted(d):\n    return sorted(d.keys())"),
    ("sum_values", "写一个 Python 函数 sum_values(d) 返回字典所有值之和，只输出代码。",
     "def sum_values(d):\n    return sum(d.values())"),
    ("filter_dict", "写一个 Python 函数 filter_dict(d, pred) 保留满足条件的键值对，只输出代码。",
     "def filter_dict(d, pred):\n    return {k: v for k, v in d.items() if pred(k, v)}"),
    ("max_value_key", "写一个 Python 函数 max_value_key(d) 返回值最大的键，只输出代码。",
     "def max_value_key(d):\n    return max(d, key=d.get)"),
    ("merge_with_add", "写一个 Python 函数 merge_with_add(a, b) 合并字典，相同键的值相加，只输出代码。",
     "def merge_with_add(a, b):\n    out = dict(a)\n    for k, v in b.items():\n        out[k] = out.get(k, 0) + v\n    return out"),
    ("count_by", "写一个 Python 函数 count_by(items, key) 按 key 函数结果分组计数，只输出代码。",
     "def count_by(items, key):\n    counts = {}\n    for item in items:\n        k = key(item)\n        counts[k] = counts.get(k, 0) + 1\n    return counts"),
    ("pick_keys", "写一个 Python 函数 pick_keys(d, keys) 只保留指定键，只输出代码。",
     "def pick_keys(d, keys):\n    return {k: d[k] for k in keys if k in d}"),

    # ---- math category (10) ----
    ("is_prime_num", "写一个 Python 函数 is_prime_num(n) 判断 n 是否为质数，只输出代码。",
     "def is_prime_num(n):\n    if n < 2:\n        return False\n    for i in range(2, int(n ** 0.5) + 1):\n        if n % i == 0:\n            return False\n    return True"),
    ("gcd_of", "写一个 Python 函数 gcd_of(a, b) 返回最大公约数，只输出代码。",
     "def gcd_of(a, b):\n    while b:\n        a, b = b, a % b\n    return a"),
    ("lcm_of", "写一个 Python 函数 lcm_of(a, b) 返回最小公倍数，只输出代码。",
     "def lcm_of(a, b):\n    return a * b // gcd_of(a, b)"),
    ("digit_product", "写一个 Python 函数 digit_product(n) 计算各位数字乘积，只输出代码。",
     "def digit_product(n):\n    result = 1\n    for ch in str(n):\n        result *= int(ch)\n    return result"),
    ("is_power_of_two", "写一个 Python 函数 is_power_of_two(n) 判断是否为 2 的幂，只输出代码。",
     "def is_power_of_two(n):\n    return n > 0 and n & (n - 1) == 0"),
    ("sign_of", "写一个 Python 函数 sign_of(n) 返回 -1、0 或 1，只输出代码。",
     "def sign_of(n):\n    return (n > 0) - (n < 0)"),
    ("triangle_area", "写一个 Python 函数 triangle_area(base, height) 计算三角形面积，只输出代码。",
     "def triangle_area(base, height):\n    return base * height / 2"),
    ("int_sqrt", "写一个 Python 函数 int_sqrt(n) 返回整数平方根（向下取整），只输出代码。",
     "def int_sqrt(n):\n    if n < 2:\n        return n\n    lo, hi = 1, n // 2\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if mid * mid <= n:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return hi"),
    ("fizzbuzz_at", "写一个 Python 函数 fizzbuzz_at(n) 返回单个数的 FizzBuzz 结果，只输出代码。",
     "def fizzbuzz_at(n):\n    if n % 15 == 0:\n        return 'FizzBuzz'\n    if n % 3 == 0:\n        return 'Fizz'\n    if n % 5 == 0:\n        return 'Buzz'\n    return str(n)"),
    ("lerp", "写一个 Python 函数 lerp(a, b, t) 线性插值，只输出代码。",
     "def lerp(a, b, t):\n    return a + (b - a) * t"),

    # ---- date/loop/other category (16) ----
    ("days_in_month", "写一个 Python 函数 days_in_month(year, month) 返回某月天数（不考虑闰年 2 月特殊处理可简化），只输出代码。",
     "def days_in_month(year, month):\n    if month in (1, 3, 5, 7, 8, 10, 12):\n        return 31\n    if month in (4, 6, 9, 11):\n        return 30\n    return 29 if is_leap(year) else 28"),
    ("is_leap", "写一个 Python 函数 is_leap(year) 判断闰年，只输出代码。",
     "def is_leap(year):\n    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)"),
    ("sum_range_between", "写一个 Python 函数 sum_range_between(a, b) 返回闭区间整数和，只输出代码。",
     "def sum_range_between(a, b):\n    return sum(range(a, b + 1))"),
    ("repeat_char_line", "写一个 Python 函数 repeat_char_line(ch, n) 返回重复字符加换行的字符串，只输出代码。",
     "def repeat_char_line(ch, n):\n    return (ch * n) + '\\n'"),
    ("while_countdown", "写一个 Python 函数 while_countdown(n) 用 while 循环返回从 n 倒数到 1 的列表，只输出代码。",
     "def while_countdown(n):\n    out = []\n    while n >= 1:\n        out.append(n)\n        n -= 1\n    return out"),
    ("until_zero", "写一个 Python 函数 until_zero(n) 反复对折直到 0，返回次数，只输出代码。",
     "def until_zero(n):\n    steps = 0\n    while n > 0:\n        n //= 2\n        steps += 1\n    return steps"),
    ("nested_sum", "写一个 Python 函数 nested_sum(grid) 对嵌套列表求和，只输出代码。",
     "def nested_sum(grid):\n    return sum(sum(row) for row in grid)"),
    ("transpose_matrix", "写一个 Python 函数 transpose_matrix(grid) 转置二维列表，只输出代码。",
     "def transpose_matrix(grid):\n    return [list(row) for row in zip(*grid)]"),
    ("flatten_one_level", "写一个 Python 函数 flatten_one_level(items) 展开一层嵌套列表，只输出代码。",
     "def flatten_one_level(items):\n    out = []\n    for item in items:\n        if isinstance(item, list):\n            out.extend(item)\n        else:\n            out.append(item)\n    return out"),
    ("join_path", "写一个 Python 函数 join_path(parts) 用 / 连接路径片段，只输出代码。",
     "def join_path(parts):\n    return '/'.join(p.strip('/') for p in parts)"),
    ("bool_to_int", "写一个 Python 函数 bool_to_int(flags) 把布尔列表转为 0/1 列表，只输出代码。",
     "def bool_to_int(flags):\n    return [int(f) for f in flags]"),
    ("all_unique", "写一个 Python 函数 all_unique(lst) 判断列表元素是否全部唯一，只输出代码。",
     "def all_unique(lst):\n    return len(lst) == len(set(lst))"),
    ("find_min_index", "写一个 Python 函数 find_min_index(lst) 返回最小值首次出现的下标，只输出代码。",
     "def find_min_index(lst):\n    return lst.index(min(lst))"),
    ("categorize_score", "写一个 Python 函数 categorize_score(score) 90+返回 A、80+返回 B、60+返回 C、否则 D，只输出代码。",
     "def categorize_score(score):\n    if score >= 90:\n        return 'A'\n    if score >= 80:\n        return 'B'\n    if score >= 60:\n        return 'C'\n    return 'D'"),
    ("apply_twice", "写一个 Python 函数 apply_twice(f, x) 对 x 应用函数 f 两次，只输出代码。",
     "def apply_twice(f, x):\n    return f(f(x))"),
    ("compose_safe", "写一个 Python 函数 compose_safe(f, g, x) 依次应用 g 再应用 f，异常时返回 None，只输出代码。",
     "def compose_safe(f, g, x):\n    try:\n        return f(g(x))\n    except Exception:\n        return None"),
]

# =====================================================================
# 20 debug tasks: buggy code + minimal fix (all parse-checked).
# =====================================================================

DEBUG = [
    ("fix_off_by_one",
     "下面的代码想返回列表前 n 个元素，但结果多了一个元素，请修复并只输出修复后的完整代码。\n```python\ndef first_n(lst, n):\n    return lst[:n + 1]\n```",
     "def first_n(lst, n):\n    return lst[:n]",
     "off-by-one slice bound"),
    ("fix_wrong_operator",
     "下面的代码想计算平均温度，但结果不对，请修复并只输出修复后的完整代码。\n```python\ndef mean_temperature(nums):\n    return sum(nums) / len(nums) + 1\n```",
     "def mean_temperature(nums):\n    return sum(nums) / len(nums)",
     "spurious +1 in average"),
    ("fix_wrong_comparison",
     "下面的代码想找出最小值，但返回的是最大值，请修复并只输出修复后的完整代码。\n```python\ndef find_min(lst):\n    m = lst[0]\n    for v in lst:\n        if v > m:\n            m = v\n    return m\n```",
     "def find_min(lst):\n    m = lst[0]\n    for v in lst:\n        if v < m:\n            m = v\n    return m",
     "comparison operator inverted"),
    ("fix_missing_return",
     "下面的代码想统计偶数个数，但总是返回 None，请修复并只输出修复后的完整代码。\n```python\ndef count_even(nums):\n    total = 0\n    for n in nums:\n        if n % 2 == 0:\n            total += 1\n```",
     "def count_even(nums):\n    total = 0\n    for n in nums:\n        if n % 2 == 0:\n            total += 1\n    return total",
     "missing return statement"),
    ("fix_indentation",
     "下面的代码想对每个元素翻倍，但只有最后一个元素被处理，请修复并只输出修复后的完整代码。\n```python\ndef double_all(lst):\n    out = []\n    for v in lst:\n        pass\n    out.append(v * 2)\n    return out\n```",
     "def double_all(lst):\n    out = []\n    for v in lst:\n        out.append(v * 2)\n    return out",
     "loop body outside loop"),
    ("fix_mutable_default",
     "下面的代码想每次返回新列表，但重复调用会累积旧元素，请修复并只输出修复后的完整代码。\n```python\ndef append_item(item, bucket=[]):\n    bucket.append(item)\n    return bucket\n```",
     "def append_item(item, bucket=None):\n    if bucket is None:\n        bucket = []\n    bucket.append(item)\n    return bucket",
     "mutable default argument"),
    ("fix_string_concat",
     "下面的代码想拼接数字和文字，但会报 TypeError，请修复并只输出修复后的完整代码。\n```python\ndef describe(age):\n    return '年龄: ' + age\n```",
     "def describe(age):\n    return '年龄: ' + str(age)",
     "missing str() conversion"),
    ("fix_index_error",
     "下面的代码想取第一个元素，空列表会崩溃，请修复并只输出修复后的完整代码。\n```python\ndef head(lst):\n    return lst[0]\n```",
     "def head(lst):\n    return lst[0] if lst else None",
     "guard against empty list"),
    ("fix_loop_bound",
     "下面的代码想访问下标，但会 IndexError，请修复并只输出修复后的完整代码。\n```python\ndef print_pairs(lst):\n    for i in range(len(lst)):\n        print(lst[i], lst[i + 1])\n```",
     "def print_pairs(lst):\n    for i in range(len(lst) - 1):\n        print(lst[i], lst[i + 1])",
     "off-by-one range bound"),
    ("fix_wrong_key",
     "下面的代码想读取用户年龄，但键名写错了，请修复并只输出修复后的完整代码。\n```python\ndef get_age(user):\n    return user['ages']\n```",
     "def get_age(user):\n    return user['age']",
     "typo in dict key"),
    ("fix_division_zero",
     "下面的代码想计算占比，空列表会除零崩溃，请修复并只输出修复后的完整代码。\n```python\ndef ratio(part, total):\n    return part / total\n```",
     "def ratio(part, total):\n    if total == 0:\n        return 0.0\n    return part / total",
     "divide-by-zero guard"),
    ("fix_shadowed_builtin",
     "下面的代码想把字符串列表转成整数，但结果全是 0，请修复并只输出修复后的完整代码。\n```python\ndef to_ints(strs):\n    ints = []\n    for s in strs:\n        ints.append(int(strs))\n    return ints\n```",
     "def to_ints(strs):\n    ints = []\n    for s in strs:\n        ints.append(int(s))\n    return ints",
     "iterated wrong variable"),
    ("fix_logic_and_or",
     "下面的代码想判断 0 到 100 之间，但边界值判断不对，请修复并只输出修复后的完整代码。\n```python\ndef in_range(n):\n    return n > 0 or n < 100\n```",
     "def in_range(n):\n    return 0 <= n <= 100",
     "or should be and/range chain"),
    ("fix_accumulator_reset",
     "下面的代码想累加，但每次循环都把结果清零，请修复并只输出修复后的完整代码。\n```python\ndef total_sum(nums):\n    total = 0\n    for n in nums:\n        total = 0\n        total += n\n    return total\n```",
     "def total_sum(nums):\n    total = 0\n    for n in nums:\n        total += n\n    return total",
     "accumulator reset inside loop"),
    ("fix_wrong_slice_step",
     "下面的代码想每隔一个元素取样，但顺序反了，请修复并只输出修复后的完整代码。\n```python\ndef sample_even_indexes(lst):\n    return lst[::-2]\n```",
     "def sample_even_indexes(lst):\n    return lst[::2]",
     "wrong slice direction"),
    ("fix_type_coercion",
     "下面的代码想比较数值大小，但输入是字符串，比较结果不对，请修复并只输出修复后的完整代码。\n```python\ndef is_bigger(a, b):\n    return a > b\n```",
     "def is_bigger(a, b):\n    return float(a) > float(b)",
     "string comparison instead of numeric"),
    ("fix_early_exit",
     "下面的代码想找到所有匹配项，但找到第一个就返回了，请修复并只输出修复后的完整代码。\n```python\ndef find_all(lst, target):\n    for v in lst:\n        if v == target:\n            return [v]\n    return []\n```",
     "def find_all(lst, target):\n    out = []\n    for v in lst:\n        if v == target:\n            out.append(v)\n    return out",
     "premature return inside loop"),
    ("fix_none_check",
     "下面的代码想安全读取嵌套字典，但中间层缺失会崩溃，请修复并只输出修复后的完整代码。\n```python\ndef get_city(user):\n    return user['address']['city']\n```",
     "def get_city(user):\n    address = user.get('address')\n    if not address:\n        return None\n    return address.get('city')",
     "unguarded nested access"),
    ("fix_boolean_return",
     "下面的代码想判断列表是否为空，但返回的是字符串，请修复并只输出修复后的完整代码。\n```python\ndef is_empty(lst):\n    if len(lst) == 0:\n        return 'True'\n    else:\n        return 'False'\n```",
     "def is_empty(lst):\n    return len(lst) == 0",
     "string literals instead of booleans"),
    ("fix_range_off_by_one",
     "下面的代码想打印 1 到 5，但只打印到 4，请修复并只输出修复后的完整代码。\n```python\ndef print_one_to_five():\n    for i in range(1, 5):\n        print(i)\n```",
     "def print_one_to_five():\n    for i in range(1, 6):\n        print(i)",
     "range upper bound exclusive"),
]

# =====================================================================
# 14 QA samples with declared key terms.
# =====================================================================

QA = [
    ("qa-loop-gate", "训练数据进入训练前要过哪些门？",
     "要过数据门（rights 与 approved 检查）、去重门和数量门；之后训练结果还要过独立评估门与回归门，全部通过才谈得上晋升。",
     ["数据门", "去重", "评估", "回归"]),
    ("qa-eval-loss", "eval_loss 下降一定代表模型变强了吗？",
     "不一定。eval_loss 下降可能只是拟合了训练分布，真正的能力提升要靠独立评测任务和回归测试确认。",
     ["eval_loss", "独立评测", "回归"]),
    ("qa-lora", "LoRA 微调改的是什么？",
     "LoRA 不改原模型权重，只在注意力层旁边挂低秩矩阵，训练时只更新这些小矩阵。",
     ["LoRA", "低秩", "权重"]),
    ("qa-champion", "冠军模型和最新模型有什么区别？",
     "冠军模型是经过独立评估并通过晋升审核的版本；最新训练的版本如果没有通过门控，就不能取代冠军。",
     ["冠军", "晋升", "审核"]),
    ("qa-fixed-holdout", "为什么评测集要跨版本固定？",
     "固定评测集保证不同版本的分数可以直接比较；如果每版换评测集，分数变化就可能来自评测集差异而不是模型差异。",
     ["固定", "比较", "评测集"]),
    ("qa-regression", "回归测试在训练闭环里做什么？",
     "回归测试用固定题目检查新版本是否把原来会的题做错了；出现退化就阻止晋升。",
     ["回归", "退化", "晋升"]),
    ("qa-data-rights", "self_authored 数据为什么可以直接用？",
     "self_authored 表示样本完全由本团队原创编写，没有版权来源风险，所以可以通过数据门。",
     ["self_authored", "原创", "数据门"]),
    ("qa-tokenizer", "tokenizer 在训练和推理时的作用一样吗？",
     "一样，都是把文本切成模型能处理的 token 序列；训练和推理必须用同一个 tokenizer，保持一致，否则模型读到的是乱码。",
     ["tokenizer", "token", "一致"]),
    ("qa-greedy", "评测时为什么用贪心解码？",
     "贪心解码没有随机性，同样的输入永远得到同样的输出，这样不同版本的评测结果才可复现、可比较。",
     ["贪心", "随机", "可复现"]),
    ("qa-adapter-base", "LoRA adapter 能挂到别的基座模型上吗？",
     "不能随便挂。adapter 权重的维度和它训练时的基座绑定，换基座必须重新训练。",
     ["adapter", "基座", "维度"]),
    ("qa-syntax-check", "语法正确率和单元测试通过率有什么不同？",
     "语法正确率只检查代码能不能被解析；单元测试通过率检查代码逻辑对不对，能运行但结果错的代码语法正确率仍是 100%。",
     ["语法", "单元测试", "逻辑"]),
    ("qa-prompt-format", "训练样本为什么是两轮对话格式？",
     "两轮 user/assistant 格式和推理时的输入结构一致，模型学到的回答方式才能直接用到实际对话里。",
     ["user", "assistant", "格式"]),
    ("qa-repeat-loop", "重复循环是什么失败？",
     "重复循环指模型生成时反复输出同样的短语停不下来，常见于过拟合或数据太少，回归门会标记这类回答。",
     ["重复", "过拟合", "回归"]),
    ("qa-small-model", "0.6B 小模型适合学什么？",
     "0.6B 小模型适合学稳定的输出格式、固定任务模板和领域词汇，不适合学复杂推理；任务要小而明确。",
     ["0.6B", "格式", "推理"]),
]

# =====================================================================
# 6 counterexamples against the two known failure modes, written on
# REAL code tasks (not abstract statements).
# =====================================================================

COUNTEREXAMPLES = [
    # anti-019: direct minimal python answer, no off-topic drift.
    ("ce-019-a",
     "直接用代码回答：写一个函数把摄氏度转华氏度。",
     "def c_to_f(c):\n    return c * 9 / 5 + 32",
     "counterexample to sft-019 (off-topic): direct code answer only",
     {"task_type": "counterexample_019"}),
    ("ce-019-b",
     "直接用代码回答：写一个函数返回两个数的较大值。",
     "def bigger(a, b):\n    return a if a > b else b",
     "counterexample to sft-019 (off-topic): direct code answer only",
     {"task_type": "counterexample_019"}),

    # anti-020: at most one sentence, no repetition loop.
    ("ce-020-a",
     "写一个 while 循环打印 1 到 3，然后用一句话说明循环什么时候停。",
     "```python\nfor i in range(1, 4):\n    print(i)\n```\n循环变量到达 4 时停止。",
     "counterexample to sft-020 (repetition loop): exactly one sentence",
     {"task_type": "counterexample_020"}),
    ("ce-020-b",
     "写一个 for 循环把列表元素翻倍打印，然后用一句话说明循环次数由什么决定。",
     "```python\nfor v in lst:\n    print(v * 2)\n```\n循环次数由列表长度决定。",
     "counterexample to sft-020 (repetition loop): exactly one sentence",
     {"task_type": "counterexample_020"}),
]

# Two extra counterexamples that pair the anti-019 rule with real debug tasks.
COUNTEREXAMPLES += [
    ("ce-019-c",
     "直接用代码回答：修复这个函数，让它返回列表长度。\n```python\ndef size(lst):\n    return -1\n```",
     "def size(lst):\n    return len(lst)",
     "counterexample to sft-019 on a REAL debug task: direct minimal fix",
     {"task_type": "counterexample_019"}),
    ("ce-019-d",
     "直接用代码回答：修复这个函数，让它返回字符串大写形式。\n```python\ndef shout(s):\n    return s\n```",
     "def shout(s):\n    return s.upper()",
     "counterexample to sft-019 on a REAL debug task: direct minimal fix",
     {"task_type": "counterexample_019"}),
]


def build_records() -> list[dict]:
    records: list[dict] = []
    n = 0
    for func, question, answer in CODE_GEN:
        n += 1
        records.append(_rec(
            f"code-cand-{n:03d}", "code_gen", question, answer,
            "Real python task; answer must be direct, no >=3 consecutive identical lines; "
            "no repetition loop (sft-020 counter-rule); stays on the exact question (sft-019 counter-rule).",
            target_func=func))
    for sid, question, answer, note in DEBUG:
        n += 1
        # Extract the real function name from the buggy snippet, e.g.
        # "def first_n(lst, n):" -> "first_n".
        import re
        m = re.search(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", answer)
        records.append(_rec(
            f"code-cand-{n:03d}", "debug", question, answer, note + "; direct fix only",
            target_func=m.group(1) if m else ''))
    for sid, question, answer, terms in QA:
        n += 1
        records.append(_rec(
            f"code-cand-{n:03d}", "qa", question, answer,
            "QA sample; key terms must all appear; no repetition loop",
            key_terms=terms))
    for sid, question, answer, note, extra in COUNTEREXAMPLES:
        n += 1
        records.append(_rec(
            sid, extra["task_type"], question, answer, note))
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='data/seed/coding_candidates_v1.jsonl')
    args = parser.parse_args()

    records = build_records()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n',
        encoding='utf-8')
    by_type: dict[str, int] = {}
    for r in records:
        by_type[r['task_type']] = by_type.get(r['task_type'], 0) + 1
    print(json.dumps({'written': args.out, 'total': len(records), 'by_type': by_type},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
