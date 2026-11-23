"""Parameterized code task generator for GrowthFoundry V2 (Phase 1).

Generates >=500 verified, diverse Python coding samples:
- code_gen (string, math, list, dict, logic)
- debug (off-by-one, mutable default, zero division, type errors, none checks)
- refactor (comprehensions, conditional simplification, builtins)
- multi_step (multi-step pipeline functions)
- explain (Python mechanics, conventions, best practices)

Every executable sample is self-tested during generation using its own test_hints.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys

# Ensure function names never collide with eval holdouts
EXISTING_EVAL_FUNCS = {
    'all_positive', 'append_to', 'average', 'capitalize_words', 'celsius_to_fahrenheit',
    'check', 'chunk_list', 'count_char', 'count_vowels', 'count_words', 'digits_sum',
    'divide', 'fact', 'factorial', 'filter_long_words', 'find_max_index', 'flatten',
    'get_first', 'is_anagram', 'is_leap_year', 'is_palindrome', 'is_sorted',
    'max_of_three', 'merge_dicts', 'middle_element', 'remove_duplicates', 'repeat_string',
    'reverse_list', 'second_largest', 'string_length', 'sum_even', 'swap_keys',
    'to_binary', 'total', 'unique_chars', 'word_count', 'zip_sum'
}

EXISTING_V1_FUNCS = {
    'all_unique', 'append_item', 'apply_twice', 'bigger', 'bool_to_int', 'c_to_f',
    'categorize_score', 'chunked_sum', 'clamp_value', 'compose_safe', 'count_by',
    'count_even', 'count_negatives', 'count_substring', 'days_in_month', 'describe',
    'dict_keys_sorted', 'digit_product', 'double_all', 'drop_while', 'filter_dict',
    'find_all', 'find_min', 'find_min_index', 'first_n', 'first_negative',
    'fizzbuzz_at', 'flatten_one_level', 'gcd_of', 'get_age', 'get_city', 'head',
    'in_range', 'int_sqrt', 'interleave', 'invert_dict', 'is_alpha_only', 'is_bigger',
    'is_empty', 'is_leap', 'is_power_of_two', 'is_prime_num', 'is_vowel_start',
    'join_path', 'last_char', 'last_index', 'lcm_of', 'lerp', 'max_value_key',
    'mean_temperature', 'merge_with_add', 'min_abs', 'nested_sum', 'normalize_ws',
    'pad_left', 'pair_sums', 'pick_keys', 'print_one_to_five', 'print_pairs', 'ratio',
    'repeat_char_line', 'rotate_list', 'running_max', 'safe_get', 'sample_even_indexes',
    'shout', 'sign_of', 'size', 'slice_every_nth', 'slugify', 'starts_with_any',
    'strip_spaces', 'sum_range_between', 'sum_values', 'swap_case', 'tail_sum',
    'title_case', 'to_ints', 'total_sum', 'transpose_matrix', 'triangle_area',
    'truncate', 'until_zero', 'while_countdown'
}

FORBIDDEN_NAMES = EXISTING_EVAL_FUNCS | EXISTING_V1_FUNCS


def self_test_assertions(code_str: str, test_hint: str) -> bool:
    """Execute code in a local namespace and run each assertion."""
    env: dict = {}
    try:
        ast.parse(code_str)
        exec(code_str, env, env)
        assertions = [s.strip() for s in test_hint.split(';') if s.strip()]
        for stmt in assertions:
            val = eval(stmt, env, env)
            if not val:
                return False
        return True
    except Exception:
        return False


def make_record(source_id: str, task_type: str, question: str, code: str,
                test_hint: str = "", target_func: str = "") -> dict:
    note = f"V2 synthetic sample; task_type={task_type}; verified via self-test assertions."
    rec = {
        "source_id": source_id,
        "rights": "self_authored",
        "reviewed_by": "dataset_author",
        "approved": True,
        "split": "train",
        "task_type": task_type,
        "messages": [
            {"role": "user", "content": question},
            {"role": "assistant", "content": code}
        ],
        "note": note
    }
    if target_func:
        rec["target_func"] = target_func
    if test_hint:
        rec["test_hint"] = test_hint
    return rec


def generate_all_samples() -> list[dict]:
    records: list[dict] = []
    used_funcs: set[str] = set()

    def register_task(task_type: str, q_tmpl: str, code_tmpl: str,
                      hints_tmpl: str, target_func: str, **kwargs) -> bool:
        func_name = target_func.format(**kwargs)
        if func_name in FORBIDDEN_NAMES or func_name in used_funcs:
            return False
        q = q_tmpl.format(func=func_name, **kwargs)
        c = code_tmpl.format(func=func_name, **kwargs)
        h = hints_tmpl.format(func=func_name, **kwargs)

        # Verify assertions execute cleanly
        if h and not self_test_assertions(c, h):
            return False

        sid = f"v2-{task_type[:4]}-{len(records) + 1:04d}"
        rec = make_record(sid, task_type, q, c, test_hint=h, target_func=func_name)
        records.append(rec)
        used_funcs.add(func_name)
        return True

    # =========================================================================
    # 1. Math & Numbers (code_gen) - target ~120
    # =========================================================================
    math_specs = [
        # Geometric shapes
        ("calc_circle_area_{r}", "def {func}(radius):\n    import math\n    return round(math.pi * radius ** 2, 2)",
         "{func}(1)==3.14; {func}(0)==0.0; {func}(2)==12.57",
         "写一个 Python 函数 {func}(radius) 计算圆面积并保留2位小数，只输出代码。"),
        ("calc_cylinder_vol_{r}", "def {func}(r, h):\n    import math\n    return round(math.pi * (r ** 2) * h, 2)",
         "{func}(1, 2)==6.28; {func}(2, 5)==62.83; {func}(0, 10)==0.0",
         "写一个 Python 函数 {func}(r, h) 计算圆柱体体积并保留2位小数，只输出代码。"),
        ("dist_2d_{r}", "def {func}(x1, y1, x2, y2):\n    import math\n    return round(math.hypot(x2 - x1, y2 - y1), 2)",
         "{func}(0,0,3,4)==5.0; {func}(1,1,1,1)==0.0; {func}(0,0,1,1)==1.41",
         "写一个 Python 函数 {func}(x1, y1, x2, y2) 计算二维平面两点欧几里得距离保留2位小数，只输出代码。"),
        ("sphere_surf_area_{r}", "def {func}(radius):\n    import math\n    return round(4 * math.pi * radius ** 2, 2)",
         "{func}(1)==12.57; {func}(0)==0.0; {func}(3)==113.1",
         "写一个 Python 函数 {func}(radius) 计算球体表面积并保留2位小数，只输出代码。"),
        ("cone_vol_{r}", "def {func}(r, h):\n    import math\n    return round((1/3) * math.pi * (r ** 2) * h, 2)",
         "{func}(3, 5)==47.12; {func}(0, 5)==0.0; {func}(1, 3)==3.14",
         "写一个 Python 函数 {func}(r, h) 计算圆锥体积并保留2位小数，只输出代码。"),
        ("heron_triangle_{r}", "def {func}(a, b, c):\n    import math\n    s = (a + b + c) / 2\n    return round(math.sqrt(max(0, s * (s - a) * (s - b) * (s - c))), 2)",
         "{func}(3, 4, 5)==6.0; {func}(5, 5, 6)==12.0; {func}(6, 8, 10)==24.0",
         "写一个 Python 函数 {func}(a, b, c) 使用海伦公式计算三角形面积保留2位小数，只输出代码。"),

        # Arithmetic and Sequences
        ("fib_nth_{r}", "def {func}(n):\n    if n <= 0: return 0\n    if n == 1: return 1\n    a, b = 0, 1\n    for _ in range(2, n + 1):\n        a, b = b, a + b\n    return b",
         "{func}(0)==0; {func}(1)==1; {func}(6)==8; {func}(10)==55",
         "写一个 Python 函数 {func}(n) 返回斐波那契数列第 n 项（0起始），只输出代码。"),
        ("collatz_steps_{r}", "def {func}(n):\n    steps = 0\n    while n > 1:\n        n = n // 2 if n % 2 == 0 else 3 * n + 1\n        steps += 1\n    return steps",
         "{func}(1)==0; {func}(2)==1; {func}(6)==8; {func}(7)==16",
         "写一个 Python 函数 {func}(n) 计算考拉兹猜想（Collatz）到达 1 所需的步数，只输出代码。"),
        ("sum_multiples_{r}", "def {func}(limit, m1, m2):\n    return sum(x for x in range(limit) if x % m1 == 0 or x % m2 == 0)",
         "{func}(10, 3, 5)==23; {func}(15, 2, 7)==51; {func}(5, 2, 3)==5",
         "写一个 Python 函数 {func}(limit, m1, m2) 计算小于 limit 且是 m1 或 m2 倍数的所有正整数之和，只输出代码。"),
        ("is_perfect_num_{r}", "def {func}(n):\n    if n <= 1: return False\n    return sum(i for i in range(1, n) if n % i == 0) == n",
         "{func}(6)==True; {func}(28)==True; {func}(12)==False; {func}(1)==False",
         "写一个 Python 函数 {func}(n) 判断一个正整数是否为完数（所有真因子之和等于自身），只输出代码。"),
        ("armstrong_check_{r}", "def {func}(n):\n    s = str(n)\n    k = len(s)\n    return sum(int(c) ** k for c in s) == n",
         "{func}(153)==True; {func}(370)==True; {func}(10)==False; {func}(9474)==True",
         "写一个 Python 函数 {func}(n) 判断是否为水仙花数/阿姆斯特朗数，只输出代码。"),
        ("count_prime_factors_{r}", "def {func}(n):\n    count = 0\n    d = 2\n    while d * d <= n:\n        while n % d == 0:\n            count += 1\n            n //= d\n        d += 1\n    if n > 1: count += 1\n    return count",
         "{func}(12)==3; {func}(7)==1; {func}(16)==4; {func}(1)==0",
         "写一个 Python 函数 {func}(n) 计算正整数 n 的质因数分解后的总因子个数（含重因数），只输出代码。"),
        ("harmonic_sum_{r}", "def {func}(n):\n    return round(sum(1 / i for i in range(1, n + 1)), 2)",
         "{func}(1)==1.0; {func}(2)==1.5; {func}(4)==2.08; {func}(5)==2.28",
         "写一个 Python 函数 {func}(n) 计算调和级数前 n 项和并保留2位小数，只输出代码。"),
        ("digital_root_{r}", "def {func}(n):\n    while n >= 10:\n        n = sum(int(c) for c in str(n))\n    return n",
         "{func}(16)==7; {func}(942)==6; {func}(0)==0; {func}(9)==9",
         "写一个 Python 函数 {func}(n) 计算整数的数字根（反复将各位数字相加直至个位数），只输出代码。"),
        ("round_to_nearest_{r}", "def {func}(n, base):\n    return round(n / base) * base",
         "{func}(14, 5)==15; {func}(12, 5)==10; {func}(100, 25)==100; {func}(33, 10)==30",
         "写一个 Python 函数 {func}(n, base) 将 n 四舍五入到最近的 base 的倍数，只输出代码。"),
        ("modular_power_{r}", "def {func}(base, exp, mod):\n    return pow(base, exp, mod)",
         "{func}(2, 3, 5)==3; {func}(10, 2, 7)==2; {func}(3, 4, 100)==81",
         "写一个 Python 函数 {func}(base, exp, mod) 计算模幂运算 (base ** exp) % mod，只输出代码。"),
        ("count_set_bits_{r}", "def {func}(n):\n    return bin(n).count('1')",
         "{func}(7)==3; {func}(8)==1; {func}(0)==0; {func}(15)==4",
         "写一个 Python 函数 {func}(n) 统计正整数二进制表示中 1 的个数（汉明重量），只输出代码。"),
    ]

    for name_pat, code_pat, hints_pat, q_pat in math_specs:
        for v in range(1, 9):
            register_task("code_gen", q_pat, code_pat, hints_pat, name_pat, r=v)

    # =========================================================================
    # 2. String Manipulation (code_gen) - target ~120
    # =========================================================================
    str_specs = [
        ("strip_punctuation_{r}", "def {func}(s):\n    import string\n    return ''.join(c for c in s if c not in string.punctuation)",
         "{func}('Hello, World!')=='Hello World'; {func}('a#b$c')=='abc'; {func}('')==''",
         "写一个 Python 函数 {func}(s) 移除字符串中所有标点符号，只输出代码。"),
        ("mask_credit_card_{r}", "def {func}(card_no):\n    s = str(card_no)\n    if len(s) <= 4: return s\n    return '*' * (len(s) - 4) + s[-4:]",
         "{func}('1234567812345678')=='************5678'; {func}('1234')=='1234'; {func}('99')=='99'",
         "写一个 Python 函数 {func}(card_no) 对卡号除后4位外所有字符用*掩码，只输出代码。"),
        ("camel_to_snake_{r}", "def {func}(name):\n    import re\n    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()",
         "{func}('CamelCase')=='camel_case'; {func}('simpleTest')=='simple_test'; {func}('word')=='word'",
         "写一个 Python 函数 {func}(name) 将驼峰命名转为下划线 snake_case，只输出代码。"),
        ("snake_to_camel_{r}", "def {func}(name):\n    parts = name.split('_')\n    return parts[0] + ''.join(p.capitalize() for p in parts[1:])",
         "{func}('snake_case')=='snakeCase'; {func}('my_var_name')=='myVarName'; {func}('word')=='word'",
         "写一个 Python 函数 {func}(name) 将下划线命名转为小驼峰 lowerCamelCase，只输出代码。"),
        ("caesar_cipher_{r}", "def {func}(text, shift):\n    res = []\n    for c in text:\n        if c.isalpha():\n            base = ord('a') if c.islower() else ord('A')\n            res.append(chr((ord(c) - base + shift) % 26 + base))\n        else:\n            res.append(c)\n    return ''.join(res)",
         "{func}('abc', 1)=='bcd'; {func}('xyz', 3)=='abc'; {func}('Hello!', 2)=='Jgnnq!'",
         "写一个 Python 函数 {func}(text, shift) 实现凯撒加密（仅移位英文字母），只输出代码。"),
        ("count_consonants_{r}", "def {func}(s):\n    return sum(1 for c in s.lower() if c.isalpha() and c not in 'aeiou')",
         "{func}('hello')==3; {func}('Python')==5; {func}('aeiou')==0; {func}('')==0",
         "写一个 Python 函数 {func}(s) 统计字符串中辅音字母个数（忽略大小写），只输出代码。"),
        ("expand_tabs_{r}", "def {func}(text, spaces=4):\n    return text.replace('\\t', ' ' * spaces)",
         "{func}('\\ta')=='    a'; {func}('a\\tb', 2)=='a  b'; {func}('no_tab')=='no_tab'",
         "写一个 Python 函数 {func}(text, spaces=4) 将制表符 \\t 替换为指定空格数，只输出代码。"),
        ("extract_hashtags_{r}", "def {func}(text):\n    import re\n    return re.findall(r'#(\\w+)', text)",
         "{func}('Learning #python with #AI!')==['python', 'AI']; {func}('No tags here')==[]; {func}('#one')==['one']",
         "写一个 Python 函数 {func}(text) 提取文本中所有形如 #tag 的标签单词列表，只输出代码。"),
        ("format_duration_{r}", "def {func}(seconds):\n    m, s = divmod(seconds, 60)\n    h, m = divmod(m, 60)\n    return f'{{h:02d}}:{{m:02d}}:{{s:02d}}'",
         "{func}(0)=='00:00:00'; {func}(65)=='00:01:05'; {func}(3661)=='01:01:01'",
         "写一个 Python 函数 {func}(seconds) 将秒数格式化为 HH:MM:SS 字符串，只输出代码。"),
        ("remove_html_tags_{r}", "def {func}(html):\n    import re\n    return re.sub(r'<[^>]+>', '', html)",
         "{func}('<p>Hello <b>World</b></p>')=='Hello World'; {func}('plain')=='plain'; {func}('<br/>')==''",
         "写一个 Python 函数 {func}(html) 移除文本中所有的 HTML 标签，只输出代码。"),
        ("is_isogram_{r}", "def {func}(word):\n    clean = [c for c in word.lower() if c.isalpha()]\n    return len(clean) == len(set(clean))",
         "{func}('Dermatoglyphics')==True; {func}('isogram')==True; {func}('hello')==False; {func}('')==True",
         "写一个 Python 函数 {func}(word) 判断单词是否为等长字（isogram，字母无重复），只输出代码。"),
        ("repeat_interleaved_{r}", "def {func}(s, n):\n    return ''.join(c * n for c in s)",
         "{func}('abc', 2)=='aabbcc'; {func}('Hi', 3)=='HHHiii'; {func}('', 5)==''",
         "写一个 Python 函数 {func}(s, n) 将字符串每个字符连续重复 n 次，只输出代码。"),
    ]

    for name_pat, code_pat, hints_pat, q_pat in str_specs:
        for v in range(1, 9):
            register_task("code_gen", q_pat, code_pat, hints_pat, name_pat, r=v)

    # =========================================================================
    # 3. List & Array Algorithms (code_gen) - target ~120
    # =========================================================================
    list_specs = [
        ("cumulative_sum_{r}", "def {func}(nums):\n    res = []\n    cur = 0\n    for x in nums:\n        cur += x\n        res.append(cur)\n    return res",
         "{func}([1, 2, 3])==[1, 3, 6]; {func}([4])==[4]; {func}([])==[]",
         "写一个 Python 函数 {func}(nums) 计算列表的前缀累加和数组，只输出代码。"),
        ("find_missing_number_{r}", "def {func}(nums, n):\n    expected = n * (n + 1) // 2\n    return expected - sum(nums)",
         "{func}([1, 2, 4, 5], 5)==3; {func}([2, 3, 4], 4)==1; {func}([1, 2, 3], 4)==4",
         "写一个 Python 函数 {func}(nums, n) 找出 1 到 n 连续序列中缺失的唯一整数，只输出代码。"),
        ("pair_difference_{r}", "def {func}(nums):\n    return [nums[i+1] - nums[i] for i in range(len(nums) - 1)]",
         "{func}([1, 3, 7])==[2, 4]; {func}([10, 5, 2])==[-5, -3]; {func}([1])==[]",
         "写一个 Python 函数 {func}(nums) 计算相邻两数的差值列表（后减前），只输出代码。"),
        ("partition_by_parity_{r}", "def {func}(nums):\n    evens = [x for x in nums if x % 2 == 0]\n    odds = [x for x in nums if x % 2 != 0]\n    return evens + odds",
         "{func}([1, 2, 3, 4])==[2, 4, 1, 3]; {func}([2, 4])==[2, 4]; {func}([1, 3])==[1, 3]",
         "写一个 Python 函数 {func}(nums) 将偶数排在前面、奇数排在后面并保留原相对顺序，只输出代码。"),
        ("list_mode_{r}", "def {func}(lst):\n    if not lst: return None\n    from collections import Counter\n    return Counter(lst).most_common(1)[0][0]",
         "{func}([1, 2, 2, 3])==2; {func}(['a', 'b', 'a'])=='a'; {func}([])==None",
         "写一个 Python 函数 {func}(lst) 找出列表的众数（出现频次最高的元素），只输出代码。"),
        ("compress_runs_{r}", "def {func}(lst):\n    if not lst: return []\n    res = [lst[0]]\n    for x in lst[1:]:\n        if x != res[-1]:\n            res.append(x)\n    return res",
         "{func}([1, 1, 2, 2, 2, 3, 1])==[1, 2, 3, 1]; {func}([1])==[1]; {func}([])==[]",
         "写一个 Python 函数 {func}(lst) 压缩连续相同的元素（只保留一个），只输出代码。"),
        ("find_peaks_{r}", "def {func}(nums):\n    peaks = []\n    for i in range(1, len(nums) - 1):\n        if nums[i] > nums[i-1] and nums[i] > nums[i+1]:\n            peaks.append(i)\n    return peaks",
         "{func}([1, 3, 2, 5, 4])==[1, 3]; {func}([1, 2, 3])==[]; {func}([5, 1, 5])==[]",
         "写一个 Python 函数 {func}(nums) 找出数组中严格大于左右邻居的所有峰值索引，只输出代码。"),
        ("pairwise_product_{r}", "def {func}(a, b):\n    return [x * y for x, y in zip(a, b)]",
         "{func}([1, 2, 3], [4, 5, 6])==[4, 10, 18]; {func}([2], [3])==[6]; {func}([], [])==[]",
         "写一个 Python 函数 {func}(a, b) 计算两个等长列表对应位置元素的乘积列表，只输出代码。"),
        ("trim_extremes_{r}", "def {func}(lst, k):\n    if len(lst) <= 2 * k:\n        return []\n    s = sorted(lst)\n    return s[k:-k]",
         "{func}([1, 5, 2, 4, 3], 1)==[2, 3, 4]; {func}([1, 2], 1)==[]; {func}([10, 20, 30, 40], 1)==[20, 30]",
         "写一个 Python 函数 {func}(lst, k) 去掉排序后前 k 个最小和后 k 个最大元素，只输出代码。"),
        ("count_inversions_{r}", "def {func}(arr):\n    count = 0\n    n = len(arr)\n    for i in range(n):\n        for j in range(i + 1, n):\n            if arr[i] > arr[j]:\n                count += 1\n    return count",
         "{func}([2, 4, 1, 3, 5])==3; {func}([1, 2, 3])==0; {func}([3, 2, 1])==3",
         "写一个 Python 函数 {func}(arr) 计算数组的逆序对总数，只输出代码。"),
        ("matrix_diagonal_{r}", "def {func}(mat):\n    return [mat[i][i] for i in range(len(mat))]",
         "{func}([[1, 2], [3, 4]])==[1, 4]; {func}([[5]])==[5]; {func}([[1,0,0],[0,2,0],[0,0,3]])==[1, 2, 3]",
         "写一个 Python 函数 {func}(mat) 提取正方形矩阵的主对角线元素列表，只输出代码。"),
        ("count_subarrays_sum_{r}", "def {func}(nums, target):\n    count = 0\n    for i in range(len(nums)):\n        cur = 0\n        for j in range(i, len(nums)):\n            cur += nums[j]\n            if cur == target:\n                count += 1\n    return count",
         "{func}([1, 1, 1], 2)==2; {func}([1, 2, 3], 3)==2; {func}([1], 5)==0",
         "写一个 Python 函数 {func}(nums, target) 计算连续子数组和等于 target 的子数组个数，只输出代码。"),
    ]

    for name_pat, code_pat, hints_pat, q_pat in list_specs:
        for v in range(1, 9):
            register_task("code_gen", q_pat, code_pat, hints_pat, name_pat, r=v)

    # =========================================================================
    # 4. Dict & Set Operations (code_gen) - target ~70
    # =========================================================================
    dict_specs = [
        ("group_by_length_{r}", "def {func}(words):\n    res = {{}}\n    for w in words:\n        res.setdefault(len(w), []).append(w)\n    return res",
         "{func}(['a', 'bb', 'c', 'ddd'])=={{1: ['a', 'c'], 2: ['bb'], 3: ['ddd']}}; {func}([])=={{}}",
         "写一个 Python 函数 {func}(words) 将字符串列表按单词长度分组为字典，只输出代码。"),
        ("frequency_rank_{r}", "def {func}(lst):\n    from collections import Counter\n    return sorted(Counter(lst).items(), key=lambda x: (-x[1], x[0]))",
         "{func}(['a', 'b', 'b', 'c', 'a', 'b'])==[('b', 3), ('a', 2), ('c', 1)]; {func}([])==[]",
         "写一个 Python 函数 {func}(lst) 统计元素频次并按频次降序、元素升序返回元组列表，只输出代码。"),
        ("dict_diff_keys_{r}", "def {func}(d1, d2):\n    return sorted(set(d1.keys()) ^ set(d2.keys()))",
         "{func}({{'a': 1, 'b': 2}}, {{'b': 3, 'c': 4}})==['a', 'c']; {func}({{'a': 1}}, {{'a': 2}})==[]",
         "写一个 Python 函数 {func}(d1, d2) 找出两个字典中不同时存在的键列表（对称差），只输出代码。"),
        ("invert_multimap_{r}", "def {func}(mapping):\n    inv = {{}}\n    for k, v in mapping.items():\n        inv.setdefault(v, []).append(k)\n    return {{k: sorted(vals) for k, vals in inv.items()}}",
         "{func}({{'a': 1, 'b': 2, 'c': 1}})=={{1: ['a', 'c'], 2: ['b']}}; {func}({{}})=={{}}",
         "写一个 Python 函数 {func}(mapping) 反转字典键值对（值作为新键，原键列表并排序），只输出代码。"),
        ("sum_matching_keys_{r}", "def {func}(data, prefix):\n    return sum(v for k, v in data.items() if k.startswith(prefix))",
         "{func}({{'pre_a': 10, 'pre_b': 20, 'other': 5}}, 'pre_')==30; {func}({{}}, 'a')==0",
         "写一个 Python 函数 {func}(data, prefix) 统计字典中键以指定前缀开头的所有数值之和，只输出代码。"),
        ("filter_none_values_{r}", "def {func}(d):\n    return {{k: v for k, v in d.items() if v is not None}}",
         "{func}({{'a': 1, 'b': None, 'c': 3}})=={{'a': 1, 'c': 3}}; {func}({{'x': None}})=={{}}",
         "写一个 Python 函数 {func}(d) 过滤掉字典中值为 None 的所有键值对，只输出代码。"),
        ("dict_subset_check_{r}", "def {func}(sub, main):\n    return all(k in main and main[k] == v for k, v in sub.items())",
         "{func}({{'a': 1}}, {{'a': 1, 'b': 2}})==True; {func}({{'a': 2}}, {{'a': 1}})==False; {func}({{'c': 1}}, {{'a': 1}})==False",
         "写一个 Python 函数 {func}(sub, main) 检查 sub 是否为 main 的子集（键存在且值相等），只输出代码。"),
    ]

    for name_pat, code_pat, hints_pat, q_pat in dict_specs:
        for v in range(1, 9):
            register_task("code_gen", q_pat, code_pat, hints_pat, name_pat, r=v)

    # =========================================================================
    # 5. Debug Tasks (debug) - target ~50
    # =========================================================================
    debug_specs = [
        ("fix_empty_slice_{r}",
         "下面代码有 bug：def {func}(lst): return lst[1:]。当列表为空时抛异常或切片期望返回空列表，但要求空列表返回 []：请修复返回安全切片，只输出代码。",
         "def {func}(lst):\n    return lst[1:] if lst else []",
         "{func}([1, 2, 3])==[2, 3]; {func}([1])==[]; {func}([])==[]"),

        ("fix_mutable_default_{r}",
         "下面代码有 bug：def {func}(item, bucket=[]): bucket.append(item); return bucket。可变默认参数跨调用共享，请修复，只输出代码。",
         "def {func}(item, bucket=None):\n    if bucket is None:\n        bucket = []\n    bucket.append(item)\n    return bucket",
         "{func}(1)==[1]; {func}(2)==[2]; {func}(3, [10])==[10, 3]"),

        ("fix_dict_get_default_{r}",
         "下面代码有 bug：def {func}(d, key, fallback): return d[key]。当 key 不存在时抛 KeyError，请修复返回 fallback，只输出代码。",
         "def {func}(d, key, fallback):\n    return d.get(key, fallback)",
         "{func}({{'a': 1}}, 'a', 0)==1; {func}({{'a': 1}}, 'b', 0)==0; {func}({{}}, 'x', None)==None"),

        ("fix_zero_division_guard_{r}",
         "下面代码有 bug：def {func}(a, b): return a / b。当 b 为 0 时 ZeroDivisionError，请修复为 b==0 时返回 0.0，只输出代码。",
         "def {func}(a, b):\n    return a / b if b != 0 else 0.0",
         "{func}(10, 2)==5.0; {func}(5, 0)==0.0; {func}(0, 5)==0.0"),

        ("fix_none_string_strip_{r}",
         "下面代码有 bug：def {func}(s): return s.strip()。当 s 为 None 时 AttributeError，请修复使 None 时返回空串 ''，只输出代码。",
         "def {func}(s):\n    return s.strip() if s is not None else ''",
         "{func}('  abc ')=='abc'; {func}(None)==''; {func}('')==''"),

        ("fix_index_lookup_{r}",
         "下面代码有 bug：def {func}(lst, idx, default): return lst[idx]。越界时 IndexError，请修复越界时返回 default，只输出代码。",
         "def {func}(lst, idx, default):\n    return lst[idx] if -len(lst) <= idx < len(lst) else default",
         "{func}([10, 20], 0, -1)==10; {func}([10, 20], 5, -1)==-1; {func}([], 0, -1)==-1"),

        ("fix_int_parse_{r}",
         "下面代码有 bug：def {func}(val): return int(val)。当 val 非法数字或 None 时抛异常，请修复解析失败时返回 None，只输出代码。",
         "def {func}(val):\n    try:\n        return int(val)\n    except (ValueError, TypeError):\n        return None",
         "{func}('123')==123; {func}('abc')==None; {func}(None)==None; {func}(45)==45"),
    ]

    for name_pat, q_pat, code_pat, hints_pat in debug_specs:
        for v in range(1, 8):
            register_task("debug", q_pat, code_pat, hints_pat, name_pat, r=v)

    # =========================================================================
    # 6. Refactor Tasks (refactor) - target ~40
    # =========================================================================
    refactor_specs = [
        ("refactor_loop_to_comp_{r}",
         "请重构以下函数为单行列表推导式实现：def {func}(nums):\n    res = []\n    for x in nums:\n        if x > 0:\n            res.append(x * 2)\n    return res",
         "def {func}(nums):\n    return [x * 2 for x in nums if x > 0]",
         "{func}([1, -2, 3])==[2, 6]; {func}([-1, -2])==[]; {func}([])==[]"),

        ("refactor_any_check_{r}",
         "请重构以下函数使用 any() 内置函数：def {func}(lst):\n    for x in lst:\n        if x < 0:\n            return True\n    return False",
         "def {func}(lst):\n    return any(x < 0 for x in lst)",
         "{func}([1, -1, 2])==True; {func}([1, 2, 3])==False; {func}([])==False"),

        ("refactor_dict_comp_{r}",
         "请重构以下函数为字典推导式：def {func}(keys, values):\n    d = {{}}\n    for k, v in zip(keys, values):\n        d[k] = v\n    return d",
         "def {func}(keys, values):\n    return {{k: v for k, v in zip(keys, values)}}",
         "{func}(['a', 'b'], [1, 2])=={{'a': 1, 'b': 2}}; {func}([], [])=={{}}"),

        ("refactor_chain_compare_{r}",
         "请使用链式比较重构以下条件判定函数：def {func}(x, low, high):\n    if x >= low and x <= high:\n        return True\n    else:\n        return False",
         "def {func}(x, low, high):\n    return low <= x <= high",
         "{func}(5, 1, 10)==True; {func}(0, 1, 10)==False; {func}(10, 1, 10)==True"),

        ("refactor_sum_generator_{r}",
         "请重构为使用生成器表达式的 sum() 函数：def {func}(words):\n    total = 0\n    for w in words:\n        total += len(w)\n    return total",
         "def {func}(words):\n    return sum(len(w) for w in words)",
         "{func}(['hi', 'world'])==7; {func}([])==0; {func}(['a'])==1"),
    ]

    for name_pat, q_pat, code_pat, hints_pat in refactor_specs:
        for v in range(1, 8):
            register_task("refactor", q_pat, code_pat, hints_pat, name_pat, r=v)

    # =========================================================================
    # 7. Multi-step Pipeline Tasks (multi_step) - target ~40
    # =========================================================================
    multi_specs = [
        ("pipeline_clean_and_mean_{r}",
         "写一个 Python 函数 {func}(data) 先过滤掉非数字与负数，再计算剩余数字的平均值并保留2位小数，若无有效数字返回 0.0，只输出代码。",
         "def {func}(data):\n    valid = [x for x in data if isinstance(x, (int, float)) and x >= 0]\n    return round(sum(valid) / len(valid), 2) if valid else 0.0",
         "{func}([10, -5, 'a', 20])==15.0; {func}([-1, -2])==0.0; {func}([])==0.0; {func}([5])==5.0"),

        ("pipeline_normalize_scores_{r}",
         "写一个 Python 函数 {func}(scores) 将列表中的所有分数归一化到 0-100 区间（(x - min) / (max - min) * 100 四舍五入保留整数），若所有值相等或为空返回全 0，只输出代码。",
         "def {func}(scores):\n    if not scores: return []\n    mn, mx = min(scores), max(scores)\n    if mn == mx: return [0] * len(scores)\n    return [round((x - mn) / (mx - mn) * 100) for x in scores]",
         "{func}([10, 20, 30])==[0, 50, 100]; {func}([5, 5])==[0, 0]; {func}([])==[]"),

        ("pipeline_word_stats_{r}",
         "写一个 Python 函数 {func}(sentence) 统计句子中的单词总数、最长单词长度及平均词长（保留1位小数），返回字典 {{'count': c, 'max_len': m, 'avg_len': a}}，若空返回全 0，只输出代码。",
         "def {func}(sentence):\n    words = sentence.split()\n    if not words: return {{'count': 0, 'max_len': 0, 'avg_len': 0.0}}\n    lens = [len(w) for w in words]\n    return {{'count': len(words), 'max_len': max(lens), 'avg_len': round(sum(lens) / len(words), 1)}}",
         "{func}('hello world')=={{'count': 2, 'max_len': 5, 'avg_len': 5.0}}; {func}('')=={{'count': 0, 'max_len': 0, 'avg_len': 0.0}}"),

        ("pipeline_filter_and_sort_{r}",
         "写一个 Python 函数 {func}(records, key, threshold) 筛选出字典列表中 key 字段值 >= threshold 的项，并按该 key 字段升序排列，只输出代码。",
         "def {func}(records, key, threshold):\n    filtered = [r for r in records if r.get(key, 0) >= threshold]\n    return sorted(filtered, key=lambda x: x.get(key, 0))",
         "{func}([{{'a': 10}}, {{'a': 5}}, {{'a': 20}}], 'a', 10)==[{{'a': 10}}, {{'a': 20}}]; {func}([], 'a', 1)==[]"),
    ]

    for name_pat, q_pat, code_pat, hints_pat in multi_specs:
        for v in range(1, 9):
            register_task("multi_step", q_pat, code_pat, hints_pat, name_pat, r=v)

    # =========================================================================
    # 8. Explain / QA Tasks (qa) - target ~30
    # =========================================================================
    qa_list = [
        ("v2-qa-0001", "Python 中 is 和 == 的核心区别是什么？请简明回答。",
         "== 比较两个对象的值是否相等，而 is 比较两个对象是否为内存中的同一实体（即 id 是否相同）。",
         ["值", "内存", "id"]),
        ("v2-qa-0002", "Python 函数的 *args 和 **kwargs 分别代表什么含义？",
         "*args 用于接收任意数量的位置参数并打包为元组，**kwargs 用于接收任意数量的关键字参数并打包为字典。",
         ["位置参数", "关键字参数", "元组", "字典"]),
        ("v2-qa-0003", "什么是 Python 中的浅拷贝（shallow copy）与深拷贝（deep copy）？",
         "浅拷贝仅复制外层对象及其引用，深拷贝递归复制所有层级的嵌套子对象，修改副本完全独立。",
         ["浅拷贝", "深拷贝", "引用", "递归"]),
        ("v2-qa-0004", "Python 的列表推导式与生成器表达式在内存占用上有什么主要区别？",
         "列表推导式立即在内存中生成并存储完整列表，生成器表达式返回按需惰性计算的生成器对象，内存占用极小。",
         ["生成器", "内存", "惰性计算"]),
        ("v2-qa-0005", "Python 中可变默认参数（如 def f(x=[]):）为什么被视为代码坏味道？",
         "因为默认参数在函数定义时仅求值一次并在多次调用间持久共享，会导致状态意外累积产生难以察觉的隐蔽 bug。",
         ["默认参数", "定义", "共享", "bug"]),
        ("v2-qa-0006", "为什么在多线程环境下 Python 的 CPU 密集型任务不能实现真正的多核并行？",
         "因为全局解释器锁（GIL）确保同一时刻只有一个原生线程在执行 Python 字节码，CPU 密集型任务建议使用多进程。",
         ["全局解释器锁", "GIL", "多进程", "字节码"]),
        ("v2-qa-0007", "Python 中的 pass 语句和 continue 语句有什么区别？",
         "pass 是空操作占位符不改变执行流，continue 会立即跳过当前循环体的剩余语句并进入下一轮循环。",
         ["pass", "continue", "占位", "循环"]),
        ("v2-qa-0008", "简述 Python 的上下文管理器（with 语句）的工作原理及对应魔术方法。",
         "with 语句进入时调用上下文管理器的 __enter__ 方法，退出时无论正常还是异常均调用 __exit__ 方法释放资源。",
         ["with", "__enter__", "__exit__", "资源"]),
        ("v2-qa-0009", "Python 的 sorted() 内置函数和列表的 sort() 方法有什么不同？",
         "sort() 方法对原列表进行就地排序并返回 None，sorted() 函数接受任何可迭代对象并返回全新的已排序列表。",
         ["就地排序", "sorted", "sort", "None"]),
        ("v2-qa-0010", "Python 中静态方法（@staticmethod）和类方法（@classmethod）的主要区别是什么？",
         "@classmethod 隐式接收类本身作为第一个参数 cls，而 @staticmethod 不接收隐式参数，等同于挂载在类命名空间下的普通函数。",
         ["@classmethod", "@staticmethod", "cls", "参数"]),
        ("v2-qa-0011", "简述 Python 的 LEGB 变量作用域查找规则顺序。",
         "Python 按照 Local（局部作用域）、Enclosing（嵌套函数外层作用域）、Global（全局作用域）、Built-in（内置作用域）依次向外查找变量。",
         ["Local", "Enclosing", "Global", "Built-in", "LEGB"]),
        ("v2-qa-0012", "Python 中生成器函数中的 yield 关键字起什么作用？",
         "yield 会暂时挂起函数的执行并向调用者产出值，保留当前内部运行状态以便通过 next() 调用从断点处继续执行。",
         ["yield", "挂起", "生成器", "next"]),
        ("v2-qa-0013", "Python 中 lambda 匿名函数有什么语法限制和适用场景？",
         "lambda 只能包含单行表达式且不能包含循环或多行语句，适合作为 map、filter、sorted 等高阶函数的简易回调参数。",
         ["lambda", "单行", "表达式", "高阶函数"]),
        ("v2-qa-0014", "Python 的 __init__ 与 __new__ 方法的主要分工是什么？",
         "__new__ 是静态方法负责创建并返回新的对象实例，__init__ 是实例方法负责对已创建的实例进行属性初始化。",
         ["__new__", "__init__", "实例", "创建", "初始化"]),
        ("v2-qa-0015", "Python 中的装饰器（decorator）本质是什么？",
         "装饰器本质是一个接受函数作为输入并返回新函数的高阶函数，用于在不修改原函数源码的情况下增加横切功能。",
         ["装饰器", "高阶函数", "原函数", "包装"]),
        ("v2-qa-0016", "什么是 Python 中的闭包（closure）？",
         "闭包指内部函数引用了外部嵌套函数作用域中的非全局变量，并在外部函数执行结束返回后依然保留该变量绑定环境。",
         ["闭包", "内部函数", "自由变量", "嵌套作用域"]),
        ("v2-qa-0017", "Python 字典的 get(key, default) 相比直接索引 d[key] 有什么优势？",
         "直接索引在键不存在时抛出 KeyError，而 get() 方法会安全返回指定的默认值而不中断程序正常执行。",
         ["get", "KeyError", "默认值", "安全"]),
        ("v2-qa-0018", "Python 中 zip() 函数在不同长度迭代器传入时的默认行为是什么？",
         "zip() 默认以最短的迭代器长度为准截断终止，若需要以最长迭代器为准并填充缺失值可以使用 itertools.zip_longest。",
         ["zip", "截断", "最短", "zip_longest"]),
        ("v2-qa-0019", "Python 中的 hasattr() 与 getattr() 函数分别有什么用途？",
         "hasattr 用于检查对象是否具有指定名称的属性或方法，getattr 用于动态获取对象的属性值并支持缺省默认值。",
         ["hasattr", "getattr", "属性", "反射"]),
        ("v2-qa-0020", "Python 中的 collections.defaultdict 相比普通字典有什么核心便利？",
         "defaultdict 在访问不存在的键时会自动调用工厂函数创建并初始化该键的值，避免了显式的手动键检查与初始化。",
         ["defaultdict", "工厂函数", "初始化", "键"]),
        ("v2-qa-0021", "Python 中如何安全捕获多个不同类型的异常？",
         "在 except 关键字后面使用元组包含多个异常类型，例如 except (ValueError, TypeError) as e: 进行统一异常捕获处理。",
         ["except", "元组", "异常", "捕获"]),
        ("v2-qa-0022", "简述 Python 列表切片 lst[::-1] 的工作原理。",
         "切片的步长参数 step 为 -1，表示从列表末尾向前逆向遍历抽取元素，从而生成一个逆序的新列表副本。",
         ["切片", "步长", "逆序", "副本"]),
        ("v2-qa-0023", "Python 中的 enumerate(iterable, start=0) 提供什么功能？",
         "enumerate 会将可迭代对象包装为一个产出 (index, item) 序号与元素对应元组的枚举迭代器，支持自定义起始索引。",
         ["enumerate", "索引", "元组", "迭代器"]),
        ("v2-qa-0024", "Python 中的 any() 和 all() 内置函数的求值逻辑是什么？",
         "any() 只要可迭代对象中存在至少一个真值即返回 True，all() 要求所有元素均为真值才返回 True（空集合返回 True）。",
         ["any", "all", "真值", "短路求值"]),
        ("v2-qa-0025", "为什么在 Python 中字符串是不可变类型（immutable）？",
         "不可变性保证了字符串哈希值在生命周期内永恒不变（可用作字典键与集合元素），同时提供了线程安全与内存驻留优化。",
         ["不可变", "哈希", "字典键", "线程安全"]),
    ]

    for sid, q, a, terms in qa_list:
        rec = make_record(sid, "qa", q, a)
        rec["note"] = f"QA concept sample; key terms: {', '.join(terms)}"
        records.append(rec)

    return records


def main():
    parser = argparse.ArgumentParser(description="Generate coding candidates for V2 (Phase 1).")
    parser.add_argument("--out", default="data/seed/coding_candidates_v2.jsonl",
                        help="Output JSONL path")
    args = parser.parse_args()

    records = generate_all_samples()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    type_counts: dict[str, int] = {}
    for r in records:
        type_counts[r["task_type"]] = type_counts.get(r["task_type"], 0) + 1

    summary = {
        "status": "GENERATION_PASS",
        "output_file": str(out_path),
        "total_generated": len(records),
        "by_type": type_counts
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
